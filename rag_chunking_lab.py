import csv
import json
import re
from pathlib import Path

import numpy as np
import torch
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from transformers import AutoTokenizer

# ----------------------------------------------------------------------------
# STAP 0 - Instellingen & AMD GPU Laden (DirectML)
# ----------------------------------------------------------------------------
DATA_DIR = Path("data/markdown")
QUERIES_FILE = Path("queries.json")
OUT_DIR = Path("results")
K = 5                      # aantal opgehaalde chunks
SECTION_MAX_TOKENS = 1000  # bovengrens voor 'parent' sectie bij assemblage C
SIZES = [256, 512]         # chunkgroottes in tokens
OVERLAP_RATIO = 0.10       # overlap voor fixed-size

providers = ort.get_available_providers()
provider = "DmlExecutionProvider" if "DmlExecutionProvider" in providers else "CPUExecutionProvider"
print(f"Model wordt geladen op AMD GPU met: {provider}")

# Download en laad het ONNX bestand rechtstreeks voor DirectML
onnx_path = hf_hub_download(repo_id="BAAI/bge-m3", filename="onnx/model.onnx")
ort_session = ort.InferenceSession(onnx_path, providers=[provider])

tok = AutoTokenizer.from_pretrained("BAAI/bge-m3")


# Razendsnelle token estimator voor binnen de chunkers (voorkomt tienduizenden zware tokenizer-calls)
def n_tok(text: str) -> int:
    return int(len(text.split()) * 1.3)


class DirectMLEmbeddingModel:
    def __init__(self, session, tokenizer):
        self.session = session
        self.tokenizer = tokenizer
        self.input_names = [i.name for i in session.get_inputs()]
        self.output_name = session.get_outputs()[0].name

    def encode(self, sentences, normalize_embeddings=True, batch_size=16, show_progress_bar=False):
        if isinstance(sentences, str):
            sentences = [sentences]

        all_embeddings = []
        for i in range(0, len(sentences), batch_size):
            batch = sentences[i : i + batch_size]
            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=8192,
                return_tensors="np"
            )

            onnx_inputs = {k: v for k, v in encoded.items() if k in self.input_names}
            outputs = self.session.run([self.output_name], onnx_inputs)
            token_embeddings = torch.from_numpy(outputs[0])

            # CLS token pooling voor BGE-M3 (index 0)
            embeddings = token_embeddings[:, 0, :]

            if normalize_embeddings:
                embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

            all_embeddings.append(embeddings.numpy())

        return np.vstack(all_embeddings)


model = DirectMLEmbeddingModel(ort_session, tok)


def norm(text: str) -> str:
    """Kleine letters + witruimte samenvoegen, zodat snippet-matching robuust is."""
    return re.sub(r"\s+", " ", text.lower()).strip()


# ----------------------------------------------------------------------------
# STAP 1 - Documenten laden en in secties splitsen (op koppen)
# ----------------------------------------------------------------------------
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def load_docs() -> dict:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(DATA_DIR.glob("*.md"))}


def split_sections(doc_id: str, text: str) -> list:
    sections, stack, buf = [], [], []
    path = doc_id

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append({
                "section_id": f"{doc_id}#{len(sections)}",
                "doc": doc_id,
                "path": path,
                "text": body,
            })

    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            flush()
            buf.clear()
            level = len(m.group(1))
            stack = stack[: level - 1] + [m.group(2).strip()]
            path = " > ".join([doc_id] + stack)
        else:
            buf.append(line)
    flush()
    return sections


# ----------------------------------------------------------------------------
# STAP 2 - De vier chunkers
# ----------------------------------------------------------------------------
def make_chunk(sec: dict, text: str, prefix_path: bool = False) -> dict:
    shown = f"{sec['path']}\n{text}" if prefix_path else text
    return {"text": shown, "doc": sec["doc"], "section_id": sec["section_id"], "path": sec["path"]}


def chunk_fixed(sections, max_tokens, overlap_ratio):
    overlap = int(max_tokens * overlap_ratio)
    step = max_tokens - overlap
    chunks = []
    for s in sections:
        ids = tok.encode(s["text"], add_special_tokens=False)
        i = 0
        while True:
            piece = tok.decode(ids[i: i + max_tokens]).strip()
            if piece:
                chunks.append(make_chunk(s, piece))
            if i + max_tokens >= len(ids):
                break
            i += step
    return chunks


def _units(text, max_tokens):
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if n_tok(para) > max_tokens:
            out += [x for x in re.split(r"(?<=[.!?;])\s+|\n", para) if x.strip()]
        else:
            out.append(para)
    return out


def _pack(units, max_tokens):
    groups, cur = [], []
    for u in units:
        if cur and n_tok(" ".join(cur + [u])) > max_tokens:
            groups.append(cur)
            cur = []
        cur.append(u)
    if cur:
        groups.append(cur)
    return [" ".join(g) for g in groups]


def chunk_recursive(sections, max_tokens, prefix_path=False):
    chunks = []
    for s in sections:
        for piece in _pack(_units(s["text"], max_tokens), max_tokens):
            chunks.append(make_chunk(s, piece, prefix_path))
    return chunks


def chunk_hierarchical(sections, max_tokens):
    return chunk_recursive(sections, max_tokens, prefix_path=True)


def chunk_semantic(sections, max_tokens, percentile=25):
    """Snelle en robuuste zins-gebaseerde chunker."""
    chunks = []
    for s in sections:
        sents = [x for x in re.split(r"(?<=[.!?])\s+|\n+", s["text"]) if x.strip()]
        if not sents:
            continue
        
        cur_group = []
        for sent in sents:
            test_text = " ".join(cur_group + [sent])
            if cur_group and n_tok(test_text) > max_tokens:
                chunks.append(make_chunk(s, " ".join(cur_group)))
                cur_group = [sent]
            else:
                cur_group.append(sent)
        if cur_group:
            chunks.append(make_chunk(s, " ".join(cur_group)))
    return chunks


# ----------------------------------------------------------------------------
# STAP 3 - Indexeren en ophalen
# ----------------------------------------------------------------------------
def build_index(chunks):
    return model.encode([c["text"] for c in chunks], normalize_embeddings=True,
                        batch_size=16, show_progress_bar=False)


def retrieve(query, chunks, emb, k=K):
    qv = model.encode(query, normalize_embeddings=True).flatten()
    scores = emb @ qv
    order = np.argsort(-scores)[:k]
    return [(int(i), float(scores[i])) for i in order]


# ----------------------------------------------------------------------------
# STAP 4 - Assemblagestrategieën
# ----------------------------------------------------------------------------
def label(c):
    return f"[bron: {c['path']}]"


def assemble_A(hits, chunks, sections_by_id):
    return "\n\n".join(f"{label(chunks[i])}\n{chunks[i]['text']}" for i, _ in hits)


def assemble_B(hits, chunks, sections_by_id):
    idx = sorted({i for i, _ in hits})
    return "\n\n".join(f"{label(chunks[i])}\n{chunks[i]['text']}" for i in idx)


def assemble_C(hits, chunks, sections_by_id):
    seen, blocks = set(), []
    for i, _ in hits:
        sid = chunks[i]["section_id"]
        if sid in seen:
            continue
        seen.add(sid)
        sec = sections_by_id[sid]
        ids = tok.encode(sec["text"], add_special_tokens=False)[:SECTION_MAX_TOKENS]
        blocks.append(f"[bron: {sec['path']}]\n{tok.decode(ids)}")
    return "\n\n".join(blocks)


ASSEMBLERS = {"A_score": assemble_A, "B_volgorde": assemble_B, "C_parent": assemble_C}


# ----------------------------------------------------------------------------
# STAP 5 - Metrieken
# ----------------------------------------------------------------------------
def retrieval_metrics(q, hits, chunks):
    snippets = [norm(s) for s in q["gold_snippets"]]
    found, first_rank = set(), None
    for rank, (i, _) in enumerate(hits, start=1):
        text = norm(chunks[i]["text"])
        matches = [j for j, sn in enumerate(snippets) if sn in text]
        if matches and first_rank is None:
            first_rank = rank
        found.update(matches)
    return {
        "hit": 1.0 if found else 0.0,
        "recall": len(found) / len(snippets),
        "mrr": 1.0 / first_rank if first_rank else 0.0,
    }


def context_metrics(q, context):
    snippets = [norm(s) for s in q["gold_snippets"]]
    ctx = norm(context)
    return {
        "coverage": sum(sn in ctx for sn in snippets) / len(snippets),
        "context_tokens": n_tok(context),
    }


# ----------------------------------------------------------------------------
# STAP 6 - Experiment draaien
# ----------------------------------------------------------------------------
def configs(sections):
    for size in SIZES:
        yield f"fixed_{size}", lambda s=sections, z=size: chunk_fixed(s, z, OVERLAP_RATIO)
        yield f"recursive_{size}", lambda s=sections, z=size: chunk_recursive(s, z)
        yield f"semantic_{size}", lambda s=sections, z=size: chunk_semantic(s, z)
        yield f"hierarchical_{size}", lambda s=sections, z=size: chunk_hierarchical(s, z)


def main():
    OUT_DIR.mkdir(exist_ok=True)
    docs = load_docs()
    sections = [s for d, t in docs.items() for s in split_sections(d, t)]
    sections_by_id = {s["section_id"]: s for s in sections}
    queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    answerable = [q for q in queries if q.get("answerable", True)]
    unanswerable = [q for q in queries if not q.get("answerable", True)]
    print(f"{len(docs)} documenten, {len(sections)} secties, "
          f"{len(answerable)} beantwoordbare + {len(unanswerable)} edge-case queries")

    summary, contexts, per_query = [], [], []
    for name, build in configs(sections):
        chunks = build()
        emb = build_index(chunks)
        avg_tok = np.mean([n_tok(c["text"]) for c in chunks])
        print(f"{name}: {len(chunks)} chunks, gem. {avg_tok:.0f} tokens")

        ret_rows = []
        for q in answerable:
            hits = retrieve(q["query"], chunks, emb)
            r = retrieval_metrics(q, hits, chunks)
            ret_rows.append(r)
            per_query.append({"config": name, "query_id": q["id"], "top1_score": hits[0][1],
                              "answerable": True, **r})
            for aname, fn in ASSEMBLERS.items():
                ctx = fn(hits, chunks, sections_by_id)
                cm = context_metrics(q, ctx)
                contexts.append({"config": name, "assembly": aname, "query_id": q["id"],
                                 "coverage": cm["coverage"], "context_tokens": cm["context_tokens"],
                                 "context": ctx, "score_complete_1to3": "",
                                 "score_cut_1to3": "", "score_noise_1to3": ""})

        for q in unanswerable:
            hits = retrieve(q["query"], chunks, emb)
            per_query.append({"config": name, "query_id": q["id"], "top1_score": hits[0][1],
                              "answerable": False, "hit": "", "recall": "", "mrr": ""})

        for aname in ASSEMBLERS:
            rows = [c for c in contexts if c["config"] == name and c["assembly"] == aname]
            summary.append({
                "config": name, "assembly": aname, "n_chunks": len(chunks),
                "avg_chunk_tokens": round(float(avg_tok), 1),
                "hit@K": round(np.mean([r["hit"] for r in ret_rows]), 3),
                "recall@K": round(np.mean([r["recall"] for r in ret_rows]), 3),
                "MRR": round(np.mean([r["mrr"] for r in ret_rows]), 3),
                "context_coverage": round(np.mean([r["coverage"] for r in rows]), 3),
                "avg_context_tokens": round(np.mean([r["context_tokens"] for r in rows]), 0),
            })

    for fname, rows in [("summary.csv", summary), ("per_query.csv", per_query),
                        ("contexts_for_manual_scoring.csv", contexts)]:
        with open(OUT_DIR / fname, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(rows)
    print(f"Klaar. Resultaten staan in {OUT_DIR}/")


if __name__ == "__main__":
    main()