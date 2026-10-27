# Security Policy

The Kaizumi project takes security and user safety seriously. Because Kaizumi has local desktop automation and system execution capabilities, maintaining strict boundaries against unintended or malicious execution is a core architectural priority.

---

## Supported Versions

Only the latest release on the `main` branch receives security updates.

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities via public GitHub issues.**

If you discover a potential security vulnerability in Kaizumi, please report it privately:

1. **GitHub Security Advisory:** Create a private advisory report via [GitHub Advisories](https://github.com/MusayevDoniyor/kaizumi/security/advisories/new).
2. **Email Disclosure:** Send details to **`doniyormusayev2009@gmail.com`** with the subject line: `[SECURITY] Kaizumi Vulnerability Report`.

### What to Include in Your Report:
- A clear description of the vulnerability.
- Steps to reproduce or a minimal proof of concept (PoC).
- An assessment of the potential impact (e.g., privilege escalation, arbitrary command execution, SSRF, memory leakage).
- Any proposed remediations.

### Response Timeline:
- **Initial Response:** Within 48 hours acknowledging receipt of the report.
- **Triage & Status Update:** Within 5 business days with a validation assessment.
- **Remediation & Advisory:** Once a patch is developed and verified, a security fix release will be published alongside credit to the reporter.

---

## Security Architecture Overview

Kaizumi employs defense-in-depth mechanisms designed to safeguard your local machine:

1. **Centralized Risk Model (`safety.py`):**
   - Every tool is categorized as `LOW`, `MEDIUM`, or `HIGH` risk.
   - High-risk operations (e.g., shell command execution, file deletion, process termination) cannot execute autonomously. They require explicit, out-of-band human confirmation.
2. **Cryptographic Confirmation Tokens:**
   - When a high-risk action is proposed, Kaizumi generates a single-use, unforgeable token (`confirm_token`) bound strictly to that specific action and argument set.
   - Replays or forged approvals are rejected immediately.
3. **SSRF Guard (`actions/document_qa.py`):**
   - URL fetching tools resolve DNS before connection and block private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`), link-local addresses (`169.254.0.0/16`), IPv6 loopback (`::1`), and cloud metadata services (`metadata.google.internal`).
   - Redirect chains are inspected prior to each network hop.
4. **Credential Protection & Redaction:**
   - API keys and tokens are excluded from Git via `.gitignore`.
   - The logger (`logger.py`) and memory system (`memory/memory.py`) automatically redact credentials, passwords, and authorization tokens before persisting or displaying logs.
5. **No Dynamic `exec()` / `eval()`:**
   - Desktop and terminal dispatchers employ safe declarative task mapping with keyword and regex filtering rather than unconstrained string evaluation.
