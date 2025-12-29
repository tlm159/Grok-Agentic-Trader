import os

from openai import OpenAI


class LLMClient:
    def __init__(self, base_url, model, temperature, api_key=None):
        key = api_key or os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("Missing API key. Set XAI_API_KEY in your environment.")
        self.client = OpenAI(api_key=key, base_url=base_url)
        self.model = model
        self.temperature = temperature

    def decide(self, system_prompt, user_prompt):
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip()
