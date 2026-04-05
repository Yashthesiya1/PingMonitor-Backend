"""SSL certificate checker."""
import ssl
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse


def check_ssl_certificate(url: str) -> dict:
    """
    Check SSL certificate for a URL.
    Returns dict with: is_valid, issuer, subject, valid_from, valid_to, days_remaining, error
    """
    result = {
        "is_valid": False,
        "issuer": None,
        "subject": None,
        "valid_from": None,
        "valid_to": None,
        "days_remaining": None,
        "error": None,
    }

    try:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        hostname = parsed.hostname
        port = parsed.port or 443

        if not hostname:
            result["error"] = "Invalid URL"
            return result

        if parsed.scheme != "https":
            result["error"] = "Not an HTTPS URL"
            return result

        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()

        if not cert:
            result["error"] = "No certificate returned"
            return result

        # Parse issuer
        issuer_parts = dict(x[0] for x in cert.get("issuer", []))
        result["issuer"] = issuer_parts.get("organizationName") or issuer_parts.get("commonName", "Unknown")

        # Parse subject
        subject_parts = dict(x[0] for x in cert.get("subject", []))
        result["subject"] = subject_parts.get("commonName", hostname)

        # Parse validity
        not_before = cert.get("notBefore")
        not_after = cert.get("notAfter")

        if not_before:
            valid_from = datetime.strptime(not_before, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            result["valid_from"] = valid_from

        if not_after:
            valid_to = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            result["valid_to"] = valid_to

            now = datetime.now(timezone.utc)
            days_remaining = (valid_to - now).days
            result["days_remaining"] = days_remaining
            result["is_valid"] = days_remaining > 0

    except socket.gaierror:
        result["error"] = "DNS resolution failed"
    except socket.timeout:
        result["error"] = "Connection timeout"
    except ssl.SSLCertVerificationError as e:
        result["error"] = f"Certificate verification failed: {str(e)[:200]}"
    except Exception as e:
        result["error"] = str(e)[:300]

    return result
