"""Optional installed-SDK compatibility check using an in-memory HTTP transport.

Run only after installing backend/requirements-microsoft.txt. No network, real
credential, Azure resource or billable inference is used by this script.
"""
import importlib.metadata
import json
from time import time

import httpx2
from azure.ai.projects import AIProjectClient
from azure.core.credentials import AccessToken


class LocalTestCredential:
    def get_token(self, *scopes, **kwargs):
        return AccessToken("local-fake-token", int(time()) + 3600)


requests = []


def respond(request):
    # MockTransport executes this function instead of opening a socket.
    body = json.loads(request.content)
    assert request.url.path == "/api/projects/local/openai/v1/responses"
    assert body["model"] == "local-compatibility-check"
    assert body["max_output_tokens"] == 50
    requests.append(body)
    return httpx2.Response(200, json={
        "id": "resp_local", "object": "response", "created_at": 0,
        "status": "completed", "model": "local-compatibility-check",
        "output": [{"id": "msg_local", "type": "message", "role": "assistant",
                    "status": "completed", "content": [{"type": "output_text",
                    "text": '{"reviewed":true}', "annotations": []}]}],
    })


project = AIProjectClient(
    endpoint="https://example.invalid/api/projects/local", credential=LocalTestCredential()
)
transport = httpx2.MockTransport(respond)
client = project.get_openai_client(
    http_client=httpx2.Client(transport=transport), timeout=3, max_retries=0
).with_options(timeout=3, max_retries=0)
result = client.responses.create(
    model="local-compatibility-check", input=[{"role": "system", "content": "Local SDK compatibility check"},
    {"role": "user", "content": "No inference request is sent"}], max_output_tokens=50,
)
assert json.loads(result.output_text) == {"reviewed": True}
assert len(requests) == 1
client.close()
project.close()
versions = {name: importlib.metadata.version(name) for name in ("azure-ai-projects", "azure-identity", "openai")}
print(json.dumps({"status": "passed", "versions": versions, "transport": "in-memory fake", "network_calls": 0, "billable_calls": 0}))
