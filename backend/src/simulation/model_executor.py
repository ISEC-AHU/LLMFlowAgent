"""
Model Executor - Multi-model DAG dependency generator.
Uses multiple LLMs to generate workflow dependencies from ``task_nodes`` (the
API candidate pool) and ``user_request`` for subsequent consistency analysis.
"""

import asyncio
import os
import sys
import time
import uuid
from typing import List, Dict, Optional
from dataclasses import dataclass

# Append src to the Python path for modules that import ``llm_factory``
# absolutely. Appending avoids shadowing ``backend/utils`` with ``src/utils``.
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.append(_src_dir)

from ..llm_factory.factory import LLMFactory
from ..generation.generator.dag_generator import DAGGenerator
from knowledge_service import get_selected_tool_spi_path


@dataclass
class ModelSimulationResult:
    """Generation result from one model."""
    model_name: str
    provider: str
    generated_dag: Optional[Dict] = None
    generation_time: float = 0.0
    error: Optional[str] = None


class MultiModelExecutor:
    """
    Multi-model DAG dependency generator.

    Generates ``task_links`` concurrently with multiple LLMs, giving each the
    same API candidate pool and user request, then returns all successful DAGs
    for dependency comparison.
    """

    def __init__(self):
        pass

    async def simulate_task(
        self,
        task: Dict,
        model_configs: Optional[List[Dict[str, str]]] = None,
    ) -> List[ModelSimulationResult]:
        """
        Generate DAG dependencies concurrently with multiple models.

        Args:
            task: Task data containing ``task_nodes`` and ``user_request``.
            model_configs: Model configurations. When ``None``, read the
                simulation configuration from the configuration file.

        Returns:
            Generation results from all models.
        """
        if model_configs is None:
            model_configs = LLMFactory.get_simulation_configs()

        if not model_configs:
            config = LLMFactory.get_rubric_generator_config("universal")
            model_configs = [config]

        print(f"\n🔄 Generating DAG dependencies with {len(model_configs)} models...")

        # Generate concurrently.
        coros = [
            self._generate_dag_with_model(task, config)
            for config in model_configs
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Process results.
        model_results = []
        for i, (config, result) in enumerate(zip(model_configs, results)):
            if isinstance(result, Exception):
                print(f"   ❌ Model {i+1} ({config['model']}) failed: {result}")
                model_results.append(
                    ModelSimulationResult(
                        model_name=config["model"],
                        provider=config["provider"],
                        error=str(result),
                    )
                )
            else:
                model_results.append(result)
                status = "✅" if result.generated_dag else "⚠️"
                print(f"   {status} Model {i+1} ({config['model']}) completed")

        return model_results

    async def _generate_dag_with_model(
        self,
        task: Dict,
        model_config: Dict[str, str],
    ) -> ModelSimulationResult:
        """
        Generate DAG dependencies with one model.

        Process:
        1. Extract the API candidate pool from ``task_nodes``.
        2. Generate ``task_links`` with DAGGenerator, skipping tool retrieval.
        """
        start_time = time.time()
        provider = model_config["provider"]
        model = model_config["model"]

        try:
            # Create the LLM client.
            client = LLMFactory.get_client(provider, model)

            # Extract candidates from task_nodes.
            candidate_pool = [
                node.get("task", "")
                for node in task.get("task_nodes", [])
                if node.get("task")
            ]

            if not candidate_pool:
                raise ValueError("task_nodes is empty; cannot build a candidate pool")

            # Generate DAG dependencies with DAGGenerator.
            tool_spi_path = get_selected_tool_spi_path()
            generator = DAGGenerator(
                llm_client=client,
                tool_spi_path=tool_spi_path,
            )

            case_id = task.get("id", f"sim_{uuid.uuid4().hex[:8]}")
            instruction = task.get("user_request", "")

            input_payload = {
                "id": case_id,
                "instruction": instruction,
                "candidate_pool": candidate_pool,
            }

            generated_dag = await generator.agenerate(input_payload)


            generation_time = time.time() - start_time
            print(
                f"   📝 {model}: generated DAG with "
                f"{len(generated_dag.get('task_links', []))} links "
                f"({generation_time:.1f}s)\n"
                f"   📦 {model}: {generated_dag}"
            )

            return ModelSimulationResult(
                model_name=model,
                provider=provider,
                generated_dag=generated_dag,
                generation_time=generation_time,
            )

        except Exception as e:
            print(f"   ❌ {model} generation error: {e}")
            return ModelSimulationResult(
                model_name=model,
                provider=provider,
                generation_time=time.time() - start_time,
                error=str(e),
            )
