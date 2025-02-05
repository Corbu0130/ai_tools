from time import sleep
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field
from requests import HTTPError, Response, Session


class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] = None):
        self.event_emitter = event_emitter

    async def emit(self, description="Unknown State", status="in_progress", done=False):
        if self.event_emitter:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "status": status,
                        "description": description,
                        "done": done,
                    },
                }
            )


class BaseValves(BaseModel):
    api_url: str = Field(description="Picogen API URL", default="")
    api_key: str = Field(description="Picogen API Key", default="")


class PicogenJobGenerateResponse(BaseModel):
    id: str
    cost: float


class PicogenJobGetResponse(BaseModel):
    id: str
    status: str
    payload: dict
    result: Optional[str]
    duration_ms: int
    created_at: int


class PicogenService:
    def __init__(self, emitter: EventEmitter, valves: BaseValves = BaseValves()):
        self.emitter = emitter
        self.valves = valves
        self.session = Session()
        self.session.headers.update({"API-Token": self.valves.api_key})

    async def job_generate(self, prompt: str, ratio: str = "1:1", seed: Optional[int] = None):
        try:
            await self.emitter.emit(description="Generating job")
            payload = {
                "prompt": prompt,
                "ratio": ratio,
            }
            if seed:
                payload["seed"] = seed
            response: Response = self.session.post(f"{self.valves.api_url}/job/generate", json=payload)
            response.raise_for_status()
            responses: list[PicogenJobGenerateResponse] = [PicogenJobGenerateResponse(**r) for r in response.json() if r]
            generate_response = responses[0]
            await self.emitter.emit(description="Job generated", done=True)
            return generate_response
        except HTTPError as e:
            await self.emitter.emit(description=f"Error generating job: {e.response.json()}", done=True)

            raise e
        except Exception as e:
            await self.emitter.emit(description=f"Error generating job: {e}", done=True)
            raise e

    async def job_get(self, job_id: str):
        for _ in range(10):
            try:
                await self.emitter.emit(description=f"Getting job {job_id}")
                response: Response = self.session.get(f"{self.valves.api_url}/job/get/{job_id}")
                response.raise_for_status()
                responses: list[PicogenJobGetResponse] = [PicogenJobGetResponse(**r) for r in response.json() if r]
                get_response = responses[0]

                if not get_response.result:
                    await self.emitter.emit(description=f"Retrying get job {job_id}")
                    sleep(2)
                    continue

                await self.emitter.emit(description=f"Job {job_id} retrieved", done=True)
                return get_response

            except HTTPError as e:
                await self.emitter.emit(description=f"Error getting job: {e.response.json()}", done=True)
                sleep(2)
            except Exception as e:
                await self.emitter.emit(description=f"Error getting job: {e}", done=True)
                raise Exception(f"Failed to get job {job_id}: {e}")

        raise Exception(f"Failed to get job {job_id} after 10 attempts")


class Tools:
    class Valves(BaseValves):
        pass

    def __init__(self):
        self.valves = self.Valves()

    async def generate_image(self, prompt: str, __event_emitter__: Callable[[dict], Any] = None) -> str:
        """
        Generate an image using Picogen.

        Args:
            prompt (str): The prompt to generate an image from.

        Returns:
            str: The generated image url.
        """

        emitter = EventEmitter(__event_emitter__)
        service = PicogenService(emitter, self.valves)

        try:
            response = await service.job_generate(prompt)
            response = await service.job_get(response.id)

            return response.result
        except HTTPError as e:
            return f"Error generating image: {e.response.json()}"
        except Exception as e:
            return f"Error generating image: {e}"
