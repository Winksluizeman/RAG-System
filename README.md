# RAG-System
 A selfmade RAG-system that works as a travel advisor for klm (casus).  The system has a vector database with 50 documents from the EU parlement and other travelagencies.

 The system is designed to answer questions like: "If my flight got delayed for 4 hours do i get my money back?".
 When the system receives the question it will search in a vector database with semantic searching for the best possible answers.

 Critics:
 - The revtrieval phase should be atleast 80% correct.
 - The generated answers get a minimum of 70% human approval.
 - Every claim/answer should recite a source 100% of the time.
