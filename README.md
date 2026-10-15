# LLMFlowAgent: An LLM-Based Multi-Agent Collaborative Framework for Workflow Modeling

LLMFlowAgent employs four specialized agents to emulate the iterative modeling process of human experts, enabling workflow model generation and refinement from users' natural-language descriptions.

![LLMFlowAgent multi-agent framework](images/LLMFlowAgent-framework.jpg)

## 🎥 Demonstration

For more details, you can watch the [demo video](https://youtu.be/o7lAHVpeDTg).

## ✍️ How to Use

LLMFlowAgent is publicly accessible through our [online system](http://1.13.189.179).

LLMFlowAgent provides two functional modules. The **Tool Knowledge Base** allows users to upload tool descriptions and create or select a knowledge base for workflow modeling. The **Workflow Design** module generates workflow models from natural-language descriptions and is organized into three areas: the workflow requirement and modeling settings (**Area 1**), live activity records from the four specialized agents (**Area 2**), and the generated workflow model together with its version history and evaluation scores (**Area 3**).

![LLMFlowAgent Workflow Design interface](images/screen.jpg)

### 1. Prepare a tool knowledge base

Open **Tool Knowledge Base** to select an existing knowledge base or create one by uploading a tool-description file. A knowledge base defines the tools or APIs that the system can use when constructing a workflow model.
![Tool Knowledge Base](images/tool-knowledge-base.png)

### 2. Describe the workflow

Open **Workflow Design** and enter a natural-language description of the workflow you want to build. You can also configure the acceptance threshold, maximum number of evaluation rounds, and automatic-repair option.
![Workflow requirement and settings](images/workflow-design-input.png)

### 3. Start the modeling process

Click **Start a new optimization run**. The Coordinator Agent invokes the specialized agents to generate an initial workflow model, evaluate its quality, and regenerate or repair it according to the evaluation result.

### 4. Review agent activity and provide confirmation

Follow the live activity records of the four agents. If the system identifies uncertain dependencies or asks you to choose a workflow version, respond through the confirmation dialog displayed on the page.
![Live agent activity](images/live-agent-activity.png)

### 5. Inspect the result

Inspect the generated workflow DAG, evaluation scores, evaluation report, repair history and workflow versions. The accepted or highest-scoring version is returned as the final workflow model.
![Workflow model and evaluation results](images/workflow-result.png)

## 👮‍♂️ Evaluation

The evaluation combines controlled experiments on **TaskBench** [1], a detailed case study and a user study. The benchmark experiments evaluate whether the complete multi-agent loop is more effective than direct generation or partially ablated variants and address two questions:

- **RQ1:** How accurately does LLMFlowAgent generate workflow models compared with representative baselines?
- **RQ2:** How much does each agent and the Coordinator's adaptive routing contribute to the complete framework?

### Experimental Evaluation

#### Dataset and Evaluation Evidence

We use 300 normalized workflow modeling tasks from TaskBench, a public multimedia tool-orchestration benchmark. The tasks cover image processing, audio and video conversion, and text editing. Each sample contains a natural-language requirement and a reference API workflow represented as a directed acyclic graph (DAG), where nodes denote APIs and edges denote their invocation dependencies.

The selected workflows contain an average of 3.71 nodes and 2.72 dependency edges, while the largest contains 8 nodes and 7 edges. These statistics make TaskBench suitable for evaluating both API selection and dependency construction under controlled workflow structures.

To provide consistent execution evidence, every ground-truth workflow is converted into an executable Petri net. PM4Py [2] then simulates execution traces and exports them as XES event logs. Consequently, each evaluation sample contains a natural-language description, a reference DAG, and a controlled ground-truth-derived event log.

#### Metrics

We evaluate workflow generation quality at both the component and complete-structure levels. Let N denote the number of workflow modeling tasks. For task i, G<sub>gt,i</sub> = (V<sub>gt,i</sub>, E<sub>gt,i</sub>) and G<sub>pred,i</sub> = (V<sub>pred,i</sub>, E<sub>pred,i</sub>) denote the ground-truth and generated workflow models, respectively.

##### Perfect Match Rate

Perfect Match Rate (PMR) is the percentage of tasks for which the generated workflow exactly matches the ground-truth workflow:

<div align="center">
<strong>PMR</strong> = (1 / N) × Σ<sub>i=1</sub><sup>N</sup> I(G<sub>pred,i</sub> = G<sub>gt,i</sub>)
</div>

The indicator I(·) equals 1 only when both the node set and dependency-edge set exactly match the ground truth; otherwise, it equals 0. Higher PMR is better.

##### Node and Edge F1

For X ∈ {V, E}, precision, recall, and F1 are calculated as follows:

<div align="center">
<strong>Precision(X)</strong> = |X<sub>pred</sub> ∩ X<sub>gt</sub>| / |X<sub>pred</sub>|<br>
<strong>Recall(X)</strong> = |X<sub>pred</sub> ∩ X<sub>gt</sub>| / |X<sub>gt</sub>|<br>
<strong>F1(X)</strong> = 2 × Precision(X) × Recall(X) / (Precision(X) + Recall(X))
</div>

When X = V, Node F1 evaluates the matching accuracy of activities or API nodes. When X = E, Edge F1 evaluates the matching accuracy of dependency relationships. We calculate each score per task and report the average across all tasks. Higher Node F1 and Edge F1 scores are better.

##### Simplified Graph Edit Distance

Simplified Graph Edit Distance (sGED) measures the structural difference between a generated workflow and its ground truth:

<div align="center">
<strong>sGED(G<sub>pred</sub>, G<sub>gt</sub>)</strong> = |V<sub>gt</sub> ∖ V<sub>pred</sub>| + |V<sub>pred</sub> ∖ V<sub>gt</sub>| + |E<sub>gt</sub> ∖ E<sub>pred</sub>| + |E<sub>pred</sub> ∖ E<sub>gt</sub>|
</div>

For each task, sGED counts missing nodes, redundant nodes, missing dependency edges, and redundant dependency edges. The dataset-level result is the average sGED across all tasks. Lower sGED is better.

#### Baselines

To validate its effectiveness, we compare LLMFlowAgent with five representative methods covering prompting-based, retrieval-augmented, and workflow-specific generation paradigms.

##### Few-shot [3]

Under the few-shot setting, the LLM receives the workflow requirement, the complete API list, several workflow generation examples, and a predefined JSON output schema. It then directly generates the workflow DAG.

##### Chain-of-Thought (CoT) [4]

The CoT baseline provides the LLM with the workflow requirement and complete API list and prompts it to reason step by step about the required APIs and their dependencies before generating the workflow DAG.

##### RAG+CoT [4,5]

RAG+CoT first retrieves the top-k candidate APIs from the API knowledge base according to the workflow requirement. CoT prompting is subsequently applied to select the required APIs and construct their dependency relationships.

##### ProMoAI [6]

ProMoAI employs LLMs and prompt engineering to transform natural-language process descriptions into process models. It incorporates error handling and code generation and supports interactive model refinement through user feedback.

##### LLM4Workflow [7]

LLM4Workflow retrieves relevant API knowledge according to a natural-language workflow description and employs an LLM to generate an executable workflow model.

#### Implementation Details

LLMFlowAgent and all baselines use GPT-4o as their primary generation model. For multi-model dependency analysis, LLMFlowAgent uses GPT-4o together with `deepseek-chat`, `gemini-3-flash-preview`, and `qwen-plus`. The maximum number of evaluation rounds is five. On the five-point evaluation scale, workflows scoring 1 or below are regenerated, workflows scoring above 1 but below 4 are repaired, and workflows scoring 4 or above are accepted; if no version reaches the acceptance threshold, the highest-scoring version is returned.

We construct a fixed API knowledge base from the tool summaries provided by TaskBench. Reference edges and workflow topology are excluded. Entries are encoded with `text-embedding-v2`, stored in a vector index, and reranked with `qwen3-rerank`. All methods use the same underlying tool inventory, and retrieval-based methods use the same fixed index.

#### Overall Workflow Modeling Results (RQ1)

The best and second-best results are shown in bold and underlined, respectively.

| Method | PMR (%) ↑ | Node F1 (%) ↑ | Edge F1 (%) ↑ | sGED ↓ |
|:--|--:|--:|--:|--:|
| Few-shot | 25.00 | 85.27 | 56.64 | 4.26 |
| CoT | 33.33 | 88.17 | 60.53 | 3.58 |
| RAG+CoT | 30.00 | 89.46 | 60.40 | 3.55 |
| ProMoAI | 26.67 | 87.57 | 59.49 | 4.35 |
| LLM4Workflow | <u>54.33</u> | <u>92.09</u> | <u>79.32</u> | <u>1.80</u> |
| **LLMFlowAgent** | **63.67** | **96.24** | **81.45** | **1.45** |

LLMFlowAgent achieves the best result across all four metrics. LLM4Workflow is the strongest baseline on TaskBench; compared with it, LLMFlowAgent improves PMR, Node F1, and Edge F1 by 9.34, 4.15, and 2.13 percentage points, respectively, while reducing sGED from 1.80 to 1.45, a relative reduction of 19.44%.

The improvement in Node F1 is consistent with the use of task decomposition, query rewriting, and knowledge-grounded API retrieval, which help the Generation Agent identify APIs that better match the workflow requirement. More importantly, the larger improvement in PMR indicates that the subsequent evaluation and repair process corrects critical dependency errors that prevent otherwise nearly correct DAGs from exactly matching the reference models. Overall, the results show that LLMFlowAgent improves both individual node and dependency decisions and the correctness of the complete workflow structure.

**Answer to RQ1:** LLMFlowAgent consistently outperforms all baseline methods on TaskBench. Its improvements in Edge F1, PMR, and sGED demonstrate a stronger ability to construct complete and accurate dependency structures for workflow modeling tasks.

#### Ablation Study (RQ2)

The TaskBench ablation study keeps the model and retrieval configuration of every remaining component unchanged:

- **w/o Coordinator:** replaces quality-aware routing with a fixed Generation–Evaluation–Repair sequence.
- **w/o Evaluation & Repair:** returns the Generation Agent's initial DAG without evaluation or refinement.
- **w/o Evaluation:** asks the Repair Agent to revise the requirement and current DAG without an evaluator-generated repair plan.
- **w/o Repair:** sends the Evaluation Agent's repair plan to the Generation Agent for complete DAG regeneration instead of targeted modification.

The best and second-best results are shown in bold and underlined, respectively.

| Setting | PMR (%) ↑ | Node F1 (%) ↑ | Edge F1 (%) ↑ | sGED ↓ |
|:--|--:|--:|--:|--:|
| w/o Coordinator | 62.00 | 94.51 | 80.24 | <u>1.57</u> |
| w/o Evaluation & Repair | 54.33 | 90.19 | 76.38 | 1.96 |
| w/o Evaluation | 55.67 | 90.67 | 77.57 | 1.90 |
| w/o Repair | <u>62.33</u> | <u>95.46</u> | <u>80.39</u> | 1.58 |
| **LLMFlowAgent** | **63.67** | **96.24** | **81.45** | **1.45** |

Removing any component degrades workflow generation performance, while the complete framework achieves the best result across all four metrics.

**1) Role of the Coordinator Agent.** Removing the Coordinator Agent decreases Node F1, Edge F1, and PMR by 1.73, 1.21, and 1.67 percentage points, respectively, while increasing sGED by 0.12. The fixed-sequence variant invokes Generation, Evaluation, and Repair regardless of the current workflow quality. By contrast, the Coordinator Agent routes low-quality workflows to regeneration and locally correctable workflows to targeted repair, enabling quality-aware refinement.

**2) Effect of removing Evaluation and Repair.** This variant exhibits the largest overall degradation. Node F1, Edge F1, and PMR decrease by 6.05, 5.07, and 9.34 percentage points, respectively, while sGED increases by 0.51. Without evaluation and repair, missing or redundant nodes and incorrect dependencies in the initial DAG remain undetected and uncorrected. The particularly large PMR decrease shows that the evaluation–repair loop is important for complete-structure correctness.

**3) Role of the Evaluation Agent.** Removing the Evaluation Agent decreases Node F1, Edge F1, and PMR by 5.57, 3.88, and 8.00 percentage points, respectively, while increasing sGED by 0.45. The Evaluation Agent provides more than an overall score: it uses fine-grained rubrics to localize modeling errors and translate them into concrete repair instructions. Without this guidance, the Repair Agent cannot reliably determine how the initial DAG should be modified.

**4) Role of the Repair Agent.** The w/o Repair variant obtains the best ablated Node F1, Edge F1, and PMR because the Generation Agent can partially regenerate the workflow from evaluation feedback. Nevertheless, its Node F1, Edge F1, and PMR remain 0.78, 1.06, and 1.34 percentage points below the complete framework, respectively, and its sGED is 0.13 higher. This result shows that repair-plan-guided local modifications preserve valid workflow structures more effectively than regenerating the complete DAG.

**5) Synergistic gains of the complete framework.** The Generation Agent constructs the initial workflow, the Evaluation Agent identifies fine-grained errors and formulates repair guidance, and the Repair Agent performs targeted modifications. The Coordinator Agent orchestrates their interactions and selects the next action from the evaluation result. Their complementary operation enables iterative improvement that cannot be achieved by any individual component alone.

**Answer to RQ2:** The ablation results confirm the contribution of each agent and show that their integration under the Coordinator Agent enables LLMFlowAgent to achieve the best overall workflow modeling performance.

### Case Study

We use a customer-order process from the **PMo Dataset** [8] to illustrate LLMFlowAgent's complete generation, evaluation, repair, and acceptance loop. The process begins when a customer submits an inquiry. Customer information is collected and customer concerns are addressed in parallel, and both activities must be completed before the customer is guided in selecting a product or service. The process then proceeds through quotation, order placement, order recording, and confirmation.

![Customer-order case study](images/case-study.jpg)

The Generation Agent first produces workflow **v1**. Although all required activities are present, v1 contains two redundant dependencies and three missing dependencies. Specifically, `Collect customer information -> Provide quote` and `Guide customer in selecting product/service -> Place order` are redundant, while `Address customer concerns or questions -> Guide customer in selecting product/service`, `Guide customer in selecting product/service -> Provide quote`, and `Provide quote -> Place order` are missing. These errors break the intended synchronization and allow `Provide quote` to be bypassed.

The Evaluation Agent constructs an evaluation rubric comprising nine dimensions: customer-data-flow integrity, selection-to-order gating, concern-resolution prerequisites, product selection before quotation, quote-to-order binding, activity coverage, control-flow integrity, semantic suitability, and data compatibility. It assesses v1 using the user requirement, DAG structure, tool descriptions, multi-model dependency analysis, and the selected execution log. The system aggregates the nine dimension-level evaluations on its five-point scale and reports a score of **2.7** for v1. Because this score is above the regeneration threshold of 1 but below the acceptance threshold of 4, the Coordinator Agent routes v1 and its repair plan to the Repair Agent rather than regenerating the complete workflow.

The Repair Agent performs five localized operations: it removes the two redundant dependencies and adds the three missing dependencies while preserving the correct activities and relations. Workflow **v2** therefore restores the intended parallel branches and the subsequent sequence from product selection to quotation and order placement. The Evaluation Agent reassesses v2 using the same nine dimensions, and its score increases to **4.7**. Because this score exceeds the acceptance threshold, the Coordinator Agent accepts v2 as the final workflow model.

### User Study

We conducted a user study with ten participants to assess the usability and perceived usefulness of LLMFlowAgent. The participants included five graduate students, one undergraduate student, two researchers, and two software professionals. Their workflow-modeling experience ranged from no prior experience to more than three years.

#### Procedure and Questionnaire

Each participant completed four workflow-modeling tasks selected from the PMo Dataset [8] and TaskBench [1]. Participants created or selected a tool knowledge base, submitted the natural-language requirements, inspected the generated workflows and evaluation reports, selected execution logs when requested, reviewed the repair processes, and examined the final workflows. After completing all four tasks, they rated seven statements about their overall experience using a five-point Likert scale: 1 (**Strongly disagree**), 2 (**Disagree**), 3 (**Neutral**), 4 (**Agree**), and 5 (**Strongly agree**).

![LLMFlowAgent user-study questionnaire](images/user-study-questionnaire.png)

#### Participant-Level Responses

All ten participants completed their assigned study activities. The de-identified responses are shown below.

| Participant | Role | Workflow experience | Task completed | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 | Q7 |
|:--|:--|:--|:--:|--:|--:|--:|--:|--:|--:|--:|
| P01 | Graduate student | 1–3 years | Yes | 4 | 4 | 5 | 5 | 4 | 3 | 4 |
| P02 | Researcher | More than 3 years | Yes | 4 | 4 | 5 | 5 | 5 | 4 | 4 |
| P03 | Graduate student | Less than 1 year | Yes | 4 | 5 | 4 | 4 | 4 | 5 | 4 |
| P04 | Software professional | 1–3 years | Yes | 5 | 4 | 4 | 5 | 5 | 4 | 5 |
| P05 | Graduate student | 1–3 years | Yes | 4 | 4 | 5 | 4 | 4 | 4 | 4 |
| P06 | Researcher | More than 3 years | Yes | 4 | 5 | 4 | 5 | 4 | 5 | 4 |
| P07 | Undergraduate student | Less than 1 year | Yes | 4 | 3 | 4 | 4 | 5 | 3 | 5 |
| P08 | Software professional | More than 3 years | Yes | 5 | 4 | 4 | 4 | 4 | 4 | 3 |
| P09 | Graduate student | 1–3 years | Yes | 4 | 3 | 4 | 4 | 3 | 4 | 4 |
| P10 | Graduate student | Less than 1 year | Yes | 4 | 5 | 3 | 5 | 4 | 4 | 3 |

#### User-Study Results

A rating of 4 or 5 is counted as a positive response. Mean ratings range from **4.0 to 4.5**, and 62 of the 70 item responses (**88.6%**) are positive.

| Item | Mean | Positive responses | Positive rate |
|:--:|--:|--:|--:|
| Q1 | 4.2 | 10/10 | 100% |
| Q2 | 4.1 | 8/10 | 80% |
| Q3 | 4.2 | 9/10 | 90% |
| Q4 | 4.5 | 10/10 | 100% |
| Q5 | 4.2 | 9/10 | 90% |
| Q6 | 4.0 | 8/10 | 80% |
| Q7 | 4.0 | 8/10 | 80% |

The evaluation-report item (Q4) received the highest mean rating of 4.5. Nine participants agreed or strongly agreed that the final workflow satisfied the given requirement (Q3), and eight participants agreed or strongly agreed that the system was easy to use (Q6). These descriptive results indicate that participants considered LLMFlowAgent useful and effective for workflow modeling. Because the study included only ten participants, the results should be interpreted as complementary evidence rather than as a population-level usability claim.

## 🛠️ Getting Started

Follow the steps below to run LLMFlowAgent on your local machine.

### Prerequisites

- Git
- Python 3.11
- Node.js 20 and npm
- PostgreSQL 16
- API keys for the LLM providers selected in `backend/config/llm_providers.yaml`

### 1. Clone the Repository

```bash
git clone git@github.com:ISEC-AHU/LLMFlowAgent.git
cd LLMFlowAgent
```

### 2. Prepare PostgreSQL

Start PostgreSQL and create an empty database for LLMFlowAgent:

```bash
psql -U postgres
```

Then run the following SQL command:

```sql
CREATE DATABASE llmflowagent;
```

The required tables are created automatically when the backend starts for the first time.

### 3. Configure and Start the Backend

Create and activate a Python virtual environment:

```bash
cd backend
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

On Linux or macOS:

```bash
source .venv/bin/activate
cp .env.example .env
```

Edit `backend/.env` and set the local PostgreSQL credentials and the API keys required by the selected LLM providers:

```dotenv
DB_NAME=llmflowagent
DB_USER=postgres
DB_PASSWORD=your-postgresql-password
DB_HOST=localhost
DB_PORT=5432

OPENAI_API_KEY=your-openai-key
GEMINI_API_KEY=your-gemini-key
QWEN_API_KEY=your-qwen-key
DEEPSEEK_API_KEY=your-deepseek-key
```

Provider endpoints, models, and agent-role mappings are configured in `backend/config/llm_providers.yaml`. Keep all credentials in `backend/.env` and do not commit this file.

Install the dependencies and start the backend:

```bash
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

The backend API documentation is available at <http://localhost:8000/docs>.

### 4. Start the Frontend

Open another terminal and run:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> to use LLMFlowAgent. The frontend connects to the local backend at <http://localhost:8000> by default.

## 📚 References

1. Y. Shen, K. Song, X. Tan, W. Zhang, K. Ren, S. Yuan, *et al.*, [“TaskBench: Benchmarking Large Language Models for Task Automation,”](https://proceedings.neurips.cc/paper_files/paper/2024/file/085185ea97db31ae6dcac7497616fd3e-Paper-Datasets_and_Benchmarks_Track.pdf) in *Advances in Neural Information Processing Systems*, vol. 37, pp. 4540–4574, 2024.
2. A. Berti, S. van Zelst, and D. Schuster, [“PM4Py: A Process Mining Library for Python,”](https://doi.org/10.1016/j.simpa.2023.100556) *Software Impacts*, vol. 17, Art. no. 100556, 2023.
3. T. Brown, B. Mann, N. Ryder, M. Subbiah, J. D. Kaplan, P. Dhariwal, *et al.*, [“Language Models Are Few-Shot Learners,”](https://proceedings.neurips.cc/paper_files/paper/2020/hash/1457c0d6bfcb4967418bfb8ac142f64a-Abstract.html) in *Advances in Neural Information Processing Systems*, vol. 33, pp. 1877–1901, 2020.
4. J. Wei, X. Wang, D. Schuurmans, M. Bosma, B. Ichter, F. Xia, *et al.*, [“Chain-of-Thought Prompting Elicits Reasoning in Large Language Models,”](https://proceedings.neurips.cc/paper/2022/hash/9d5609613524ecf4f15af0f7b31abca4-Abstract.html) in *Advances in Neural Information Processing Systems*, vol. 35, pp. 24824–24837, 2022.
5. P. Lewis, E. Perez, A. Piktus, F. Petroni, V. Karpukhin, N. Goyal, *et al.*, [“Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks,”](https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html) in *Advances in Neural Information Processing Systems*, vol. 33, pp. 9459–9474, 2020.
6. H. Kourani, A. Berti, D. Schuster, and W. M. P. van der Aalst, [“ProMoAI: Process Modeling with Generative AI,”](https://doi.org/10.24963/ijcai.2024/1014) in *Proceedings of the Thirty-Third International Joint Conference on Artificial Intelligence*, pp. 8708–8712, 2024.
7. J. Xu, W. Du, X. Liu, and X. Li, [“LLM4Workflow: An LLM-Based Automated Workflow Model Generation Tool,”](https://doi.org/10.1145/3691620.3695360) in *Proceedings of the 39th IEEE/ACM International Conference on Automated Software Engineering*, pp. 2394–2398, 2024.
8. A. Brissard, F. Cuppens, and A. Zouaq, [“What Is the Best Process Model Representation? A Comparative Analysis for Process Modeling with Large Language Models,”](https://arxiv.org/abs/2507.11356) in *Business Process Management Workshops*, vol. 569, pp. 55–68, 2025.
