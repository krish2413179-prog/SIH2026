"""Inference Client for the trained ML Fraud Model.
Handles communication with the model server and transforms predictions into forensic narratives.
"""

from __future__ import annotations
import logging
import httpx
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class MLPrediction:
    entity_type: str       # e.g., "CEX", "Mixer", "Unknown"
    probability: float     # 0.0 to 1.0
    reasoning: str         # Forensic explanation generated via XAI (SHAP/LIME)
    refined_score: int    # 0-100

class InferenceClient:
    """Client to interact with the external Model Inference Server."""

    def __init__(self, endpoint: str = "http://model-server:8000/predict"):
        self.endpoint = endpoint

    async def predict_vasp(self, feature_vector: list[float]) -> MLPrediction:
        """Sends feature vector to ML model and returns prediction + explanation."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.endpoint,
                    json={"features": feature_vector}
                )
                response.raise_for_status()
                data = response.json()

                return MLPrediction(
                    entity_type=data["prediction"],
                    probability=data["probability"],
                    reasoning=data["explanation"],
                    refined_score=data["refined_score"]
                )
        except Exception as e:
            logger.error("Inference Server Error: %s. Using fallback logic.", e)
            # Fallback mock for development purposes
            return self._get_mock_prediction(feature_vector)

    def _get_mock_prediction(self, vector: list[float]) -> MLPrediction:
        """Provides a simulated prediction based on basic heuristics for testing."""
        # vector[2] is fan_in_out_ratio, vector[4] is temporal_velocity
        fan_in_out = vector[2]
        velocity = vector[4]

        if fan_in_out > 10 and velocity < 3600:
            return MLPrediction(
                entity_type="CEX",
                probability=0.89,
                reasoning="Probabilistic match based on high fan-in ratio and rapid sweep velocity (<1hr).",
                refined_score=85
            )
        return MLPrediction(
            entity_type="Unknown",
            probability=0.10,
            reasoning="No strong VASP structural signatures detected.",
            refined_score=20
        )
