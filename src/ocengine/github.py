from ocengine import resource_fetcher
from ocengine import runtime
from ocengine import utils
from ocengine.fatal import EngineError
import hashlib
import json
import re

# GitHub itself allows these characters in a tag name. The anchors and the
# explicit exclusions are what make this a security boundary: nothing here can
# carry a "/", "?", "#", "%", a leading dot (so no ".."), whitespace or a
# control character into the expanded_assets URL.
TAG_NAME_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")

# The tag link as GitHub renders it, captured up to the attribute's closing
# quote so a "?query" or "#fragment" stays attached and gets rejected by
# TAG_NAME_PATTERN rather than quietly trimmed off.
RELEASE_TAG_HREF = re.compile(r"<a[^>]*?href=\"[^\"]*?/releases/tag/([^\"]*)")

# The Atom feed's <link> elements carry the same tag without the release page's
# A/B rendering. The first match is the newest release.
RELEASE_FEED_TAG = re.compile(r"<link[^>]*href=\"[^\"]*?/releases/tag/([^\"]*)")

MAX_TAG_LENGTH = 128


class InvalidReleaseTag(EngineError):
    """Scraped HTML produced something that is not a safe release tag.

    The tag is remote-controlled text that this module interpolates into the
    next request URL, so it is validated and rejected here rather than encoded,
    truncated or passed through. It is not a ``ValueError``: a caller that
    swallows the fetch failures must not swallow this one.
    """

    code = "github.invalid_release_tag"
    title = "GitHub returned an unusable release tag"


class Github:
    def __init__(self):
        self.utils = utils.Utils()
        self.fetcher = resource_fetcher.ResourceFetcher()

    def _log(self, message, level="debug"):
        # This module has never touched a terminal and must keep it that way, so
        # diagnostics go to the engine sink. NullSink makes them free.
        runtime.current_sink().log(level, "github: {}".format(message))

    def extract_payload(self, response):
        for line in response.splitlines():
            if "type=\"application/json\"" in line:
                payload = line.split(">", 1)[1].split("<", 1)[0]

                try:
                    payload = json.loads(payload)
                    payload = payload["payload"]
                except:
                    continue

                return payload
        return None
        
    def get_commits(self, owner, repo, branch="main", start_commit=None, after=-1):
        if after > -1 and not start_commit:
            start_commit = self.get_commits(owner, repo, branch)["currentCommit"]["oid"]

        if after < 0:
            url = "https://github.com/{}/{}/commits/{}".format(owner, repo, branch)
        else:
            url = "https://github.com/{}/{}/commits/{}?after={}+{}".format(owner, repo, branch, start_commit, after)

        response = self.fetcher.fetch_and_parse_content(url)

        if not response:
            raise ValueError("Failed to fetch commit information from GitHub.")

        payload = self.extract_payload(response)

        if not "commitGroups" in payload:
            raise ValueError("Cannot find commit information for repository {} on branch {}.".format(repo, branch))
        
        return payload

    def get_latest_release(self, owner, repo):
        """Return the latest release's assets, preferring GitHub's JSON API.

        The HTML releases page is rendered in more than one shape -- some
        responses carry no ``/releases/tag/`` link at all -- so scraping it was
        a build-breaking coin flip for every repository that is not in the
        build index. The API response is stable and also publishes each asset's
        SHA256 digest directly. HTML scraping remains only as the fallback for
        an API that is rate-limited or unavailable.
        """
        release = self._get_latest_release_from_api(owner, repo)
        if release is not None:
            return release
        release = self._get_latest_release_from_atom(owner, repo)
        if release is not None:
            return release
        self._log("API and feed release metadata unavailable for {}/{}; falling back to HTML".format(
            owner, repo))
        return self._get_latest_release_from_html(owner, repo)

    def _get_latest_release_from_atom(self, owner, repo):
        """Find the newest tag in the Atom feed, then read its asset list.

        This is the fallback that does not depend on the releases page's
        rendering: the feed is a stable XML document, while the page sometimes
        arrives with no tag links at all.
        """
        feed_url = "https://github.com/{}/{}/releases.atom".format(owner, repo)
        response = self.fetcher.fetch_and_parse_content(feed_url)
        if not response:
            return None

        match = RELEASE_FEED_TAG.search(response)
        if not match:
            return None
        tag_name = self._validate_tag_name(match.group(1), owner, repo)

        assets_url = "https://github.com/{}/{}/releases/expanded_assets/{}".format(
            owner, repo, tag_name)
        response = self.fetcher.fetch_and_parse_content(assets_url)
        if not response:
            return None

        assets = self._extract_assets(response, tag_name=tag_name)
        if not assets:
            return None
        return {"body": "", "assets": assets}

    def _get_latest_release_from_api(self, owner, repo):
        url = "https://api.github.com/repos/{}/{}/releases/latest".format(owner, repo)
        release = self.fetcher.fetch_and_parse_content(url, "json")
        if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
            return None

        assets = []
        for asset in release["assets"]:
            name = asset.get("name") or ""
            download_url = asset.get("browser_download_url")
            if not name or not download_url:
                continue
            upper = name.upper()
            if "tlwm" not in name and ("RESEARCH" in upper or "DEBUG" in upper):
                continue

            digest = str(asset.get("digest") or "")
            sha256 = digest.split(":", 1)[1] if digest.lower().startswith("sha256:") else None
            assets.append({
                "product_name": self.extract_asset_name(name),
                "id": asset.get("id"),
                "url": download_url,
                "sha256": sha256,
            })

        if not assets:
            return None
        return {"body": release.get("body", ""), "assets": assets}

    def _get_latest_release_from_html(self, owner, repo):
        url = "https://github.com/{}/{}/releases".format(owner, repo)
        response = self.fetcher.fetch_and_parse_content(url)

        if not response:
            raise ValueError("Failed to fetch release information from GitHub.")

        tag_name = self._extract_tag_name(response)
        body = self._extract_body_content(response)

        # The tag came out of remote HTML and is about to become part of a
        # request target. Validate it before the string is ever interpolated.
        self._validate_tag_name(tag_name, owner, repo)

        release_tag_url = "https://github.com/{}/{}/releases/expanded_assets/{}".format(owner, repo, tag_name)
        response = self.fetcher.fetch_and_parse_content(release_tag_url)

        if not response:
            raise ValueError("Failed to fetch expanded assets information from GitHub.")

        assets = self._extract_assets(response, tag_name=tag_name)

        return {
            "body": body,
            "assets": assets
        }

    def _validate_tag_name(self, tag_name, owner=None, repo=None):
        """Return the tag unchanged when it is safe to put in a URL, else raise.

        Nothing is normalized or repaired here -- an almost-valid tag is a
        remote-supplied surprise, and surprises get refused, not sanitized.
        """
        context = " for {}/{}".format(owner, repo) if owner and repo else ""
        if not isinstance(tag_name, str) or not tag_name:
            raise InvalidReleaseTag(detail="No release tag found{}.".format(context))
        if len(tag_name) > MAX_TAG_LENGTH:
            raise InvalidReleaseTag(detail=(
                "Release tag {!r} is longer than {} characters{}.".format(
                    tag_name, MAX_TAG_LENGTH, context)))
        if not TAG_NAME_PATTERN.match(tag_name):
            raise InvalidReleaseTag(detail=(
                "Refusing release tag {!r}{}: it must match {}, with no path, query, "
                "fragment, space or control characters.".format(
                    tag_name, context, TAG_NAME_PATTERN.pattern)))
        return tag_name

    def _extract_tag_name(self, response):
        # One quote-delimited pass over the whole document instead of upstream's
        # line-by-line cut: a tag that carries a newline would otherwise be
        # truncated at the line break into a *different, plausible-looking* tag,
        # and a silent rewrite of the request target is exactly what this
        # function must not do. The validator now sees the raw attribute value.
        match = RELEASE_TAG_HREF.search(response)
        return match.group(1) if match else None

    def _extract_body_content(self, response):
        for line in response.splitlines():
            if "<div" in line and "body-content" in line:
                return response.split(line.split(">", 1)[0], 1)[1].split("</div>", 1)[0][1:]
        return ""

    def _extract_assets(self, response, tag_name=None):
        assets = []

        in_li_block = False

        for line in response.splitlines():

            if "<li" in line:
                in_li_block = True
                download_link = None
                sha256 = None
                asset_id = None
            elif in_li_block and "</li" in line:
                if download_link and asset_id:
                    assets.append({
                        "product_name": self.extract_asset_name(download_link.split("/")[-1]), 
                        "id": int(asset_id), 
                        "url": "https://github.com" + download_link,
                        "sha256": sha256
                    })
                in_li_block = False

            if in_li_block:  
                if download_link is None and "<a" in line and "href=\"" in line and "/releases/download" in line:
                    download_link = line.split("href=\"", 1)[1].split("\"", 1)[0]

                    if not ("tlwm" in download_link or ("tlwm" not in download_link and "RESEARCH" not in download_link.upper() and "DEBUG" not in download_link.upper())):
                        in_li_block = False
                        continue

                if sha256 is None and "sha256:" in line:
                    sha256 = line.split("sha256:", 1)[1].split("<", 1)[0]

                if asset_id is None and "<relative-time" in line:
                    asset_id = self._generate_asset_id(line, download_link=download_link, tag_name=tag_name)

        return assets

    def _generate_asset_id(self, line, download_link=None, tag_name=None):
        """Stable cache id for one asset.

        Upstream fell back to ``random.choices`` whenever the ``datetime=``
        scrape failed, so an asset's id -- and therefore its download cache
        key -- changed on every run and nothing could be resumed or reused. The
        id is now derived from what identifies the asset: the release tag plus
        its name, falling back to the whole line. Two runs over the same release
        produce the same integers.
        """
        try:
            stamp = line.split("datetime=\"")[-1].split("\"")[0][::-1]
            digits = "".join(char for char in stamp if char.isdigit())[:9]
            if digits:
                return digits
            raise ValueError("no digits in datetime")
        except (AttributeError, IndexError, TypeError, ValueError) as exception:
            # Everything that identifies this asset, whether or not each piece was
            # scraped: two assets of the same release must not collide onto one
            # cache entry, which is the failure mode random.choices hid.
            seed = "{}|{}|{}".format(tag_name or "", download_link or "", line.strip())
            digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
            digits = "".join(char for char in digest if char.isdigit())[:9]
            if len(digits) < 6:
                # A hex digest can, rarely, carry too few digits to be a useful
                # id, so fold the digest itself into base 10 instead.
                digits = str(int(digest[:15], 16))[:9]
            self._log("no datetime on an asset line, hashed id {} ({})".format(digits, exception))
            return digits

    def extract_asset_name(self, file_name):
        end_idx = len(file_name)
        if "-" in file_name:
            end_idx = min(file_name.index("-"), end_idx)
        if "_" in file_name:
            end_idx = min(file_name.index("_"), end_idx)
        if "." in file_name:
            end_idx = min(file_name.index("."), end_idx)
            if file_name[end_idx] == "." and file_name[end_idx - 1].isdigit():
                end_idx = end_idx - 1
        asset_name = file_name[:end_idx]

        if "Sniffer" in file_name:
            asset_name = file_name.split(".")[0]
        if asset_name == "IntelBluetooth":
            asset_name = "IntelBluetoothFirmware"
        if "unsupported" in file_name:
            asset_name += "-unsupported"
        elif "rtsx" in file_name:
            asset_name += "-rtsx"
        elif "itlwm" in file_name.lower():
            if "Sequoia" in file_name:
                asset_name += "24"
            elif "Tahoe" in file_name:
                asset_name += "25"
            elif "Sonoma14.4" in file_name:
                asset_name += "23.4"
            elif "Sonoma14.0" in file_name:
                asset_name += "23.0"
            elif "Ventura" in file_name:
                asset_name += "22"
            elif "Monterey" in file_name:
                asset_name += "21"
            elif "Big_Sur" in file_name:
                asset_name += "20"
            elif "Catalina" in file_name:
                asset_name += "19"
            elif "Mojave" in file_name:
                asset_name += "18"
            elif "High_Sierra" in file_name:
                asset_name += "17"

        return asset_name