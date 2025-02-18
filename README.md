# CreditAnalysisGPT - AI-Powered Adaptive Report Generation

## Overview

CreditAnalysisGPT is an AI-driven system designed to generate comprehensive reports dynamically by analyzing data from diverse sources. While its initial scope focuses on financial analysis, the architecture is built to be **flexible and customizable**, allowing users to configure the system for any set of prompts and explore different domains beyond finance.

The system structures report generation using a **Directed Acyclic Graph (DAG)**, where each node represents a **prompt-driven data query**, and dependencies between sections are maintained. Users can interact with the system to refine the scope of analysis, leveraging real-time data sources. The final product provides an **interactive web interface**, enabling users to navigate through the report dynamically—removing irrelevant sections and expanding on topics of interest as they shape their insights in real time.

This report generation experience is akin to **walking through a dynamic knowledge landscape**, where users prune and expand their focus interactively. As they remove what they don't need and emphasize what they do, the system adapts, fetching additional context from the web to support deeper insights. In addition to textual information, the reports incorporate **images, charts, time-series visualizations, and interactive graphs**, ensuring a **rich, exploratory experience** that enhances decision-making and comprehension.

---

## Architecture

### System Components

- **Backend**: Handles data querying, processing, and integration.
- **FrontEnd**: Provides an interactive interface for exploring and refining reports.
- **DataQuerier**: Responsible for making asynchronous HTTP requests to APIs, validating JSON responses, and structuring raw data.
- **Integrator**: Implements the `generate_report` method, executing prompts in **topological order** according to the DAG. It processes queries, stores responses, and integrates results into a structured report.
- **DataMolder**: Refines raw queried data by leveraging a **Text Processing microservice**, intersecting query responses with parent node context for contextual accuracy.
- **Prompts**: Defines structured queries that guide report generation based on dependencies.

### Workflow

1. **Topological Sorting of Prompts**: The DAG defines dependencies between report sections.
2. **Data Retrieval**: Each node asynchronously queries external sources and retrieves structured data.
3. **Processing and Molding**: The retrieved data is enhanced using **context merging**, ensuring coherence.
4. **Report Composition**: The system integrates refined sections into a **structured financial report** enriched with visualizations.
5. **User Interaction**: The web interface enables users to explore topics like a **live knowledge journey**, expanding promising directions and filtering out irrelevant ones.


---

## Key Features

✅ **Asynchronous Web Data Querying** - Efficient API calls using `aiohttp`  
✅ **Dependency-Driven DAG Execution** - Ensures logical flow and proper section dependencies  
✅ **Interactive Report Customization** - Users can explore and refine topics dynamically  
✅ **Real-Time Data Processing** - Uses `Text_Processing` for context-aware refinements  
✅ **Scalable & Modular** - Designed with industry-standard architecture for extensibility  
✅ **Adaptive Exploration** - Navigate the report like a knowledge landscape, expanding relevant sections and pruning unnecessary ones  
✅ **Multi-Modal Insights** - Supports **images, charts, time-series, and interactive visualizations** for enhanced understanding  

---

## Deployment

The system is containerized using Docker for easy deployment. To run locally:

