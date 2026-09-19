def send_email_dev(to: str, subject: str, body: str) -> None:
    # ponytail: prints instead of SMTP, swap for a real mailer when deploying past dev.
    print(f"[DEV EMAIL] to={to} subject={subject!r}\n{body}")
