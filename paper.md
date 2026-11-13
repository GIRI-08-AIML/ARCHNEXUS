---
title: 'ArchNexus: A multi-agent, evidence-checked framework for automated software architecture and RFC review'
tags:
  - Python
  - software architecture
  - design review
  - large language models
  - multi-agent systems
authors:
  - name: Giridharan J A
    orcid: 0000-0000-0000-0000
    corresponding: true
    affiliation: 1
  - name: N. Gayathri
    affiliation: 1
affiliations:
  - name: Department of Artificial Intelligence and Machine Learning, Sri Shakthi Institute of Engineering and Technology, Coimbatore, India
    index: 1
date: 13 November 2026
bibliography: paper.bib
---

# Summary

ArchNexus is an open-source web application and Python service that reviews software architecture documents, commonly written as Requests for Comments (RFCs), before the software is built. Five specialist language-model agents (architecture, security, database, scalability and reliability) read the document in parallel. Every finding they report must quote the RFC word for word. The findings are then checked by deterministic code, argued over in a debate stage, and summarised by a judge agent. Fixed guardrails cap the final score and decision according to the number of critical and high-severity findings, so the verdict cannot contradict the evidence. ArchNexus provides a FastAPI backend with a PostgreSQL store, team roles, comparison of successive RFC versions, a chat assistant, Markdown and PDF export, a web dashboard and a Visual Studio Code extension. It can use a local model through Ollama or a hosted OpenAI-compatible provider.

# Statement of need

Design mistakes are cheap to fix on paper and expensive after deployment, yet design review is slow, depends on a few senior engineers and is inconsistent between reviewers. Typical gaps, such as a single server with no backups or an administrator account that shares the ordinary login, are often noticed only at deployment. Small teams and students frequently have no experienced reviewer available.

Large language models can read technical documents [@hou2024llm4se], and multi-agent debate can improve the quality of their answers [@du2023debate; @liang2024divergent]. A single chat answer, however, tends to cover only some areas and may state things the document never said. ArchNexus addresses this by giving each agent a focused role and an explicit checklist, by requiring every finding to cite the exact RFC text, and by verifying findings with ordinary code instead of trusting the model. It is intended for students, small teams and educators who want a consistent, traceable first review of a design, with the decision left to human engineers.

# Design

An uploaded PDF, Word, Markdown or text file is converted to text and split into labelled sections. The five specialist agents run concurrently and each returns up to six findings with a severity, a verbatim quote, a description, a recommendation and its trade-offs. Findings then pass through four steps: a quote guard (the quote must occur in the RFC), an evidence check (the model judges whether the RFC already addresses or contradicts the finding and may only lower its severity), a severity downgrade, and a duplicate merge based on title and quote similarity. Remaining conflicts are examined in a debate in which agents agree, disagree or refine each other's findings, in the spirit of agent debate and reflection [@du2023debate; @shinn2023reflexion]. A judge agent returns a decision and a score from 0 to 100, and guardrail code limits both: for example, three or more critical findings force a rejection with a score of at most 25. Results, debates and reports are stored so that a revised RFC can be compared with the previous review.

The project includes 108 automated tests that use a scripted model, so the pipeline, guardrails and verification steps can be tested without a live model. A GitHub Actions workflow runs the tests and a container build on every pull request.

# Limitations

Language-model output is not fully repeatable, and the quote guard checks that a quotation exists but not that the reasoning is correct. ArchNexus has not yet been benchmarked against reviews written by experts, which is planned future work. Its output is decision support and should be validated by experienced engineers.

# AI usage disclosure

Parts of the source code, tests and this paper were produced with the help of an AI assistant (Claude, by Anthropic). The authors reviewed, tested and take responsibility for all content. [Edit this section so it matches exactly how you used AI tools.]

# Acknowledgements

The authors thank their institution for support. [Add funding information, or state that there was none.]

# References
