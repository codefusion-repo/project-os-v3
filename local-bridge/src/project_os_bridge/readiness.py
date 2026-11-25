"""Bounded loopback TLS readiness shared by supervisor and worker."""
import http.client
import json


def read_metadata(context, port=8765):
    # No redirect following, proxy inheritance or external destinations.
    connection = http.client.HTTPSConnection("127.0.0.1",port,timeout=2,context=context)
    try:
        connection.request("GET","/.well-known/oauth-protected-resource/mcp")
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError("Unexpected readiness HTTP status")
        data = response.read(16385)
        if len(data)>16384:
            raise RuntimeError("Oversized readiness metadata")
        result = json.loads(data)
        if not isinstance(result,dict):
            raise RuntimeError("Invalid readiness metadata")
        return result
    finally:
        connection.close()


def verify_metadata(metadata, verifier):
    if (metadata.get("resource") != verifier.resource or
            metadata.get("authorization_servers") != [verifier.issuer]):
        raise RuntimeError("Unexpected protected resource metadata")
