"""Post one random follow-up comment on every deal in a Soluo AMS deals list.

Run:  python soluo_comments.py
Two deals next to each other in the list never get the same comment.
"""
import getpass
import http.cookiejar
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# ===== FILL THESE IN (leave one empty "" to be asked for it when the script runs) =====
LINK = ""      # deals list link, e.g. "https://soluo.aiesec.org.eg/ams/deals/?stage=131&lc=4"
USERNAME = ""  # your Soluo username
PASSWORD = ""  # your Soluo password (anyone who opens this file can read it)
# ======================================================================================

TEXTS = ["Following up", "Contacting", "Calling", "Scheduling a visit", "Meeting the owner"]
DELAY = 5  # seconds between comments
CSRF_RE = re.compile(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"')
DEAL_RE = re.compile(r'href="/ams/deals/(\d+)/')


def pick(prev):
    return random.choice([t for t in TEXTS if t != prev])


def page_path(list_url, page):
    u = urllib.parse.urlsplit(list_url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if k != "page"]
    return u.path + "?" + urllib.parse.urlencode(q + [("page", page)])


class NoPostRedirect(urllib.request.HTTPRedirectHandler):
    # A POST's redirect tells us if it worked (deal page) or not (login page), so don't follow it.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None if req.data else super().redirect_request(req, fp, code, msg, headers, newurl)


class Site:
    def __init__(self, origin, username, password):
        self.origin, self.username, self.password = origin, username, password
        self.token = None
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoPostRedirect)

    def _open(self, path, data=None):
        """Returns (path we ended on, or a POST's redirect target; page html)."""
        url, body = self.origin + path, None
        if data is not None:
            body = urllib.parse.urlencode({"csrfmiddlewaretoken": self.token, **data}).encode()
        req = urllib.request.Request(url, body, headers={"Referer": url})  # Django needs Referer on HTTPS POST
        try:
            with self.opener.open(req, timeout=30) as r:
                got, html = urllib.parse.urlsplit(r.geturl()).path, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if body is None or e.code not in (301, 302, 303):
                raise
            return urllib.parse.urlsplit(urllib.parse.urljoin(url, e.headers["Location"])).path, ""
        m = CSRF_RE.search(html)
        if m:
            self.token = m.group(1)  # Django rotates the token at login, so keep the newest
        return got, html

    def login(self):
        self._open("/login/")
        got, _ = self._open("/login/", {"username": self.username, "password": self.password, "next": "/"})
        if got.startswith("/login/"):
            raise SystemExit("Login failed: check USERNAME and PASSWORD.")
        self._open(got)  # load the page after login to pick up the new CSRF token
        print("Logged in.")

    def request(self, path, data=None):
        """GET (or POST when data is given). If the site sends us to the login page, log in and retry once."""
        got, html = self._open(path, data)
        if got.startswith("/login/"):
            print("Sent to login page, logging in again...")
            self.login()
            got, html = self._open(path, data)
        return got, html


def main():
    # GitHub Actions passes these as environment variables (from repository secrets)
    list_url = os.environ.get("SOLUO_LINK") or LINK or input("Deals list link: ").strip()
    username = os.environ.get("SOLUO_USERNAME") or USERNAME or input("Username: ").strip()
    password = os.environ.get("SOLUO_PASSWORD") or PASSWORD or getpass.getpass("Password: ")

    u = urllib.parse.urlsplit(list_url)
    site = Site(f"{u.scheme}://{u.netloc}", username, password)
    site.login()

    ids = []
    for page in range(1, 1000):
        try:
            _, html = site.request(page_path(list_url, page))
        except urllib.error.HTTPError:
            break  # past the last page
        fresh = [i for i in dict.fromkeys(DEAL_RE.findall(html)) if i not in ids]
        if not fresh:
            break
        ids += fresh
    print(f"Found {len(ids)} deals.")

    prev, fails, done = None, 0, 0
    for n, deal in enumerate(ids, 1):
        if n > 1:
            time.sleep(DELAY)
        text = pick(prev)
        try:
            got, _ = site.request(f"/ams/deals/{deal}/comments/", {"body": text})
            ok = got == f"/ams/deals/{deal}/"
        except (urllib.error.URLError, TimeoutError) as e:
            ok, got = False, str(e)
        print(f"[{n}/{len(ids)}] deal {deal}: {text} -> {'OK' if ok else 'FAILED ' + got}")
        if ok:
            prev, fails, done = text, 0, done + 1
        else:
            fails += 1
            if fails >= 3:
                raise SystemExit("Stopped: 3 failures in a row (site down or comments refused).")
    print(f"Done: {done}/{len(ids)} comments posted.")


if __name__ == "__main__":
    main()
