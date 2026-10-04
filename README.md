# LLMFlowAgent: An LLM-Based Multi-Agent Collaborative Framework for Workflow Modeling

LLMFlowAgent employs four specialized agents to emulate the iterative modeling process of human experts, enabling workflow model generation and refinement from users' natural-language descriptions.

## 🎥 Demonstration

For more details, you can watch the [demo video]().

## ✍️ How to Use

LLMFlowAgent is publicly accessible through our [online system](http://1.13.189.179).

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

Inspect the generated workflow DAG, evaluation scores, evaluation report, repair history, and workflow versions. The accepted or highest-scoring version is returned as the final workflow model.
![Workflow model and evaluation results](images/workflow-result.png)

## 👮‍♂️ Evaluation

We evaluate LLMFlowAgent on workflow modeling quality and analyze the contribution of its multi-agent components.

### Evaluation Design and Setup

**Dataset.** We use 300 normalized workflow modeling tasks from **TaskBench** [1], a public multimedia-processing benchmark released by Microsoft. The tasks cover image processing, audio and video conversion, and text editing. Each task contains a natural-language requirement and a reference workflow DAG. The selected workflows contain an average of 3.71 nodes and 2.72 dependency edges; the largest contains 8 nodes and 7 edges. To provide execution evidence, we convert the reference workflows into Petri nets and use PM4Py [2] to simulate execution traces in XES format.

**Metrics.** We report four structural metrics:

- **Node F1:** set-based F1 score for workflow-node matching.
- **Edge F1:** set-based F1 score for dependency matching.
- **Perfect Match Rate (PMR):** percentage of generated workflows whose node and edge sets both exactly match the references.
- **Simplified Graph Edit Distance (sGED):** average number of missing and redundant nodes and dependency edges; lower values are better.

**Baselines.** We compare LLMFlowAgent with five representative methods:

- **Few-shot [3]:** generates a workflow from the requirement, complete API list, and workflow examples.
- **CoT [4]:** reasons step by step about API selection and dependency construction using the complete API list.
- **RAG+CoT [4,5]:** applies CoT to the top-*k* APIs retrieved for the requirement.
- **ProMoAI [6]:** generates process models through LLM-generated code, error handling, and user-guided refinement.
- **LLM4Workflow [7]:** retrieves relevant API knowledge and generates executable workflow models.

**Implementation.** LLMFlowAgent and all baselines use GPT-4o as their primary model. Multi-model dependency analysis additionally uses `deepseek-chat`, `gemini-3-flash-preview`, `qwen-plus`, and `claude-sonnet-4-6`. The TaskBench tool summaries are used to construct the API knowledge base without reference dependencies. Knowledge entries are embedded using `text-embedding-v2` and reranked using `qwen3-rerank`. LLMFlowAgent performs at most five evaluation rounds, with regeneration and acceptance thresholds of 1 and 4, respectively, on a five-point scale.

### Workflow Modeling Performance

| Method | Node F1 (%) ↑ | Edge F1 (%) ↑ | PMR (%) ↑ | sGED ↓ |
|:--|--:|--:|--:|--:|
| Few-shot | 85.27 | 56.64 | 25.00 | 4.26 |
| CoT | 88.17 | 60.53 | 33.33 | 3.58 |
| RAG+CoT | 89.46 | 60.40 | 30.00 | 3.55 |
| ProMoAI | 87.57 | 59.49 | 26.67 | 4.35 |
| LLM4Workflow | 92.09 | 79.32 | 54.33 | 1.80 |
| **LLMFlowAgent** | **96.27** | **81.45** | **63.67** | **1.45** |

LLMFlowAgent achieves the best result across all four metrics. Compared with LLM4Workflow, the strongest baseline, it improves Node F1, Edge F1, and PMR by 4.18, 2.13, and 9.34 percentage points, respectively, while reducing sGED by 19.44%. The results show that the iterative generation–evaluation–repair process produces more accurate workflow nodes and dependencies and more frequently constructs complete workflow models that match user requirements.

### Ablation Study

We conduct an ablation study on TaskBench while retaining the same model and retrieval configurations for all remaining components:

- **w/o Coordinator:** replaces adaptive score-based routing with a fixed Generation–Evaluation–Repair sequence.
- **w/o Evaluation & Repair:** returns the initial workflow produced by the Generation Agent without evaluation or refinement.
- **w/o Evaluation:** lets the Repair Agent revise the workflow from only the requirement and current DAG, without an evaluator-generated repair plan.
- **w/o Repair:** sends the Evaluation Agent's repair plan back to the Generation Agent for complete workflow regeneration.

| Setting | Node F1 (%) ↑ | Edge F1 (%) ↑ | PMR (%) ↑ | sGED ↓ |
|:--|--:|--:|--:|--:|
| w/o Coordinator | 94.51 | 80.24 | 62.00 | 1.57 |
| w/o Evaluation & Repair | 90.19 | 76.38 | 54.33 | 1.96 |
| w/o Evaluation | 90.67 | 77.57 | 55.67 | 1.90 |
| w/o Repair | 95.46 | 80.39 | 62.33 | 1.58 |
| **LLMFlowAgent** | **96.27** | **81.45** | **63.67** | **1.45** |

Removing any component reduces performance, while the complete framework achieves the best results across all metrics. Removing both Evaluation and Repair causes the largest overall degradation, showing the importance of detecting and correcting modeling errors after generation. The Evaluation Agent provides concrete repair guidance, the Repair Agent preserves valid workflow structures through targeted modifications, and the Coordinator Agent routes workflows according to their quality. Their collaboration is therefore more effective than any ablated configuration.

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
