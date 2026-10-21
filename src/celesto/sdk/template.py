"""Public ``Template`` resource: build computers with your own packages preinstalled."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator, MutableMapping
from typing import Any

from .computer import Computer, _make_client
from .exceptions import (
    CelestoConflictError,
    CelestoNetworkError,
    CelestoRateLimitError,
    CelestoServerError,
    CelestoTemplateBuildError,
    CelestoValidationError,
)

# Statuses that mean a build is still on its way to ready or failed.
_BUILDING_STATUSES = frozenset({"queued", "building"})
# Builds are capped at 30 minutes; the rest covers time spent queued.
_DEFAULT_WAIT_TIMEOUT = 40 * 60
# wait() polls the /templates routes, which allow 60 requests a minute.
_MIN_POLL_INTERVAL = 1.0
# Longest pause between retries of a failed poll.
_MAX_RETRY_BACKOFF = 30.0


class Template(MutableMapping[str, Any]):
    """A convenience object for one custom template.

    A custom template is a built-in base template plus a shell build script.
    Creating an instance creates the template and queues its build right away;
    ``wait()`` blocks until the build is ready, and ``create_computer()``
    starts a computer from it.

    Example:
        >>> template = Template(
        ...     name="data-env",
        ...     build_script="apt-get install -y ffmpeg\\npip install pandas",
        ... )
        >>> template.wait(on_log=print)
        >>> computer = template.create_computer()
    """

    def __init__(
        self,
        *,
        name: str,
        build_script: str,
        base_template_id: str | None = None,
        default_vcpus: int | None = None,
        default_ram_mb: int | None = None,
        default_disk_size_mb: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ):
        self._client, self._owns_client = _make_client(
            client=client,
            api_key=api_key,
            base_url=base_url,
        )
        try:
            self._data: dict[str, Any] = self._client.templates.create(
                name=name,
                build_script=build_script,
                base_template_id=base_template_id,
                default_vcpus=default_vcpus,
                default_ram_mb=default_ram_mb,
                default_disk_size_mb=default_disk_size_mb,
            )
        except Exception:
            if self._owns_client:
                self._client.close()
            raise

    @classmethod
    def _wrap(cls, data: dict[str, Any], client: Any, owns_client: bool) -> Template:
        """Build an instance around existing template data without creating one."""
        instance = cls.__new__(cls)
        instance._client = client
        instance._owns_client = owns_client
        instance._data = data
        return instance

    @classmethod
    def get(
        cls,
        template_id: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> Template:
        """Load an existing custom template by its ``tpl_...`` ID."""
        sdk_client, owns_client = _make_client(
            client=client,
            api_key=api_key,
            base_url=base_url,
        )
        try:
            data = sdk_client.templates.get(template_id)
        except Exception:
            if owns_client:
                sdk_client.close()
            raise
        return cls._wrap(data, sdk_client, owns_client)

    @classmethod
    def list(
        cls,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> list[dict[str, Any]]:
        """List your organization's custom templates, newest first."""
        sdk_client, owns_client = _make_client(
            client=client,
            api_key=api_key,
            base_url=base_url,
        )
        try:
            return sdk_client.templates.list()
        finally:
            if owns_client:
                sdk_client.close()

    @classmethod
    def lint(
        cls,
        build_script: str,
        *,
        base_template_id: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Check a build script before creating a template. Nothing is built."""
        sdk_client, owns_client = _make_client(
            client=client,
            api_key=api_key,
            base_url=base_url,
        )
        try:
            return sdk_client.templates.lint(
                build_script=build_script, base_template_id=base_template_id
            )
        finally:
            if owns_client:
                sdk_client.close()

    @property
    def data(self) -> dict[str, Any]:
        """Return a copy of the latest template data."""
        return dict(self._data)

    def _identifier(self) -> str:
        identifier = self._data.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise CelestoValidationError("This template does not have an ID.")
        return identifier

    def refresh(self) -> Template:
        """Reload this template's data, including its build status."""
        self._data = self._client.templates.get(self._identifier())
        return self

    def logs(self, *, known_size: int | None = None) -> dict[str, Any]:
        """Get the end of the latest build's log. See ``wait(on_log=...)`` to follow it."""
        return self._client.templates.logs(self._identifier(), known_size=known_size)

    def wait(
        self,
        *,
        timeout: float = _DEFAULT_WAIT_TIMEOUT,
        poll_interval: float = 3,
        on_log: Callable[[str], None] | None = None,
    ) -> Template:
        """Block until the build is ready.

        Polls once every ``poll_interval`` seconds: the template's status, or,
        with ``on_log``, the build log (which carries the status too). A
        failed poll (rate limit, a 5xx answer or a network error) is retried
        with backoff until ``timeout``, since the build keeps running.

        Args:
            timeout: Seconds to wait in total. The default covers the
                30-minute build limit plus time spent queued.
            poll_interval: Seconds between polls; at least 1.
            on_log: Called with each new chunk of build log text as it arrives.

        Returns:
            This template, refreshed, with ``status`` ``ready``.

        Raises:
            CelestoTemplateBuildError: The build failed or needs a rebuild.
                ``failure`` says which script line failed, when known.
            TimeoutError: The build was still running after ``timeout``, or
                polls kept failing until then (the last error is the cause).
            CelestoValidationError: ``poll_interval`` is under 1 second, or
                either argument is NaN.
        """
        if math.isnan(timeout):
            raise CelestoValidationError("timeout must be a number of seconds.")
        if math.isnan(poll_interval) or poll_interval < _MIN_POLL_INTERVAL:
            raise CelestoValidationError(
                f"poll_interval must be at least {_MIN_POLL_INTERVAL:g} second."
            )
        deadline = time.monotonic() + timeout
        follower = _LogFollower(on_log) if on_log is not None else None
        failed_polls = 0
        while True:
            try:
                status = self._poll(follower)
            except _LogCallbackError as error:
                # The caller's on_log failed, not the API: never retry it.
                raise error.error from None
            except Exception as error:
                if not _is_transient(error):
                    raise
                failed_polls += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Template {self._identifier()} could not be checked "
                        f"before the {timeout:g}s timeout: {error}"
                    ) from error
                time.sleep(
                    min(_retry_delay(error, poll_interval, failed_polls), remaining)
                )
                continue
            failed_polls = 0
            if status == "ready":
                return self
            if status not in _BUILDING_STATUSES:
                raise _build_error(self._data)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Template {self._identifier()} was still {status} after {timeout:g}s."
                )
            time.sleep(min(poll_interval, remaining))

    def _poll(self, follower: _LogFollower | None) -> str | None:
        """Check the build once and return its status.

        With a log follower this is one request (the log answer carries the
        status); the full template is read again only once the build ends, to
        pick up the failure details and final fields.
        """
        if follower is None:
            self.refresh()
            return self._data.get("status")
        response = self.logs(known_size=follower.known_size)
        status = response.get("status")
        finished = status not in _BUILDING_STATUSES
        if finished and response.get("unchanged") and follower.holding:
            # The log stopped growing with a character held back: read it once
            # more in full so the last character is delivered.
            response = self.logs()
        follower.feed(response, finished=finished)
        if not finished:
            self._data["status"] = status
            return status
        self.refresh()
        return self._data.get("status")

    # Named edit(), not update(): Template is a MutableMapping, whose update()
    # merges keys into the local dict and must keep doing only that.
    def edit(
        self,
        *,
        name: str | None = None,
        build_script: str | None = None,
        default_vcpus: int | None = None,
        default_ram_mb: int | None = None,
        default_disk_size_mb: int | None = None,
    ) -> Template:
        """Change the name, build script or default size. Call ``rebuild()`` to build a new script."""
        self._data = self._client.templates.update(
            self._identifier(),
            name=name,
            build_script=build_script,
            default_vcpus=default_vcpus,
            default_ram_mb=default_ram_mb,
            default_disk_size_mb=default_disk_size_mb,
        )
        return self

    def rebuild(self) -> Template:
        """Rebuild with the current script and the latest base. Follow it with ``wait()``.

        Raises:
            CelestoConflictError: A build is already queued or running.
            CelestoRateLimitError: The organization already has 2 builds
                queued or running.
        """
        self._data = self._client.templates.rebuild(self._identifier())
        return self

    def delete(self) -> None:
        """Delete this template. Computers already created from it keep running."""
        self._client.templates.delete(self._identifier())

    def create_computer(self, **kwargs: Any) -> Computer:
        """Create a computer from this template.

        Takes the same keyword arguments as ``Computer(...)`` except
        ``template_id``. A template that is rebuilding still creates computers
        from its previous build.

        The computer shares this template's API client when the template was
        given one. Otherwise, or when you pass ``api_key`` or ``base_url``, it
        gets its own client, so closing the template does not close it.

        Raises:
            CelestoValidationError: The template has no ready build yet.
            CelestoTemplateBuildError: The template needs a rebuild first.
        """
        if "template_id" in kwargs:
            raise CelestoValidationError(
                "create_computer() uses this template's ID; don't pass template_id."
            )
        self._check_usable_build()
        if "client" not in kwargs:
            if self._owns_client or "api_key" in kwargs or "base_url" in kwargs:
                kwargs.setdefault("api_key", self._client.api_key)
                kwargs.setdefault("base_url", self._client.base_url)
            else:
                kwargs["client"] = self._client
        return Computer(template_id=self._identifier(), **kwargs)

    def _check_usable_build(self) -> None:
        """Fail early, with the next step, when no computer can boot this template.

        The API refuses these with 409. ``rootfs_size_mb`` is written only when
        a build succeeds and kept through rebuilds, so it says whether one exists.
        """
        status = self._data.get("status")
        if status == "needs_rebuild":
            raise _build_error(self._data)
        if status == "ready" or self._data.get("rootfs_size_mb") is not None:
            return
        if status in _BUILDING_STATUSES:
            next_step = "call wait() first"
        else:
            next_step = "fix the build script and call rebuild()"
        raise CelestoValidationError(
            f"Template {self._identifier()} has no ready build yet ({status}); {next_step}."
        )

    def close(self) -> None:
        """Close the API client if this template created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Template:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        data = self.__dict__.get("_data")
        if data is not None and name in data:
            return data[name]
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return (
            f"Template(id={self._data.get('id')!r}, name={self._data.get('name')!r}, "
            f"status={self._data.get('status')!r})"
        )


class _LogFollower:
    """Hands ``on_log`` each piece of a build log once, across polls of /logs.

    The API returns at most the last 256 KB of the log: ``log`` is the stored
    bytes from ``offset`` to ``size``, decoded with invalid bytes replaced by
    U+FFFD. Decoded text and byte counts don't line up once a replacement
    happens, so while the window stays put (``offset`` unchanged, the usual
    case) the follower counts delivered characters, which stay stable from one
    poll to the next. Only when the window slides does it convert bytes to
    characters, and that is exact unless the log has invalid bytes there.

    A poll can end in the middle of a multi-byte character, which then decodes
    as a trailing U+FFFD. That last character is held back until the next poll
    shows it whole, or the build ends.
    """

    def __init__(self, on_log: Callable[[str], None]):
        self._on_log = on_log
        # The ``offset`` of the last window read, and how many of its
        # characters were delivered.
        self._window_offset: int | None = None
        self._chars = 0
        # The log byte position delivered up to, and the last ``size`` seen.
        self._end = 0
        self._size = 0
        # Sent back as ``known_size`` so an unchanged log is not re-sent.
        self.known_size: int | None = None
        # True while a trailing character is held back for the next poll.
        self.holding = False

    def feed(self, response: dict[str, Any], *, finished: bool) -> None:
        if response.get("unchanged"):
            return
        text = response.get("log") or ""
        offset = int(response.get("offset") or 0)
        size = int(response.get("size") or 0)
        if size < self._size:
            # The log got shorter: a new build started a new log.
            self._window_offset, self._chars, self._end = None, 0, 0
        chunks = []
        if offset == self._window_offset:
            start = self._chars
        elif offset > self._end:
            # More was written between polls than the window holds.
            chunks.append(
                f"[... {offset - self._end} bytes of build log not shown ...]\n"
            )
            start = 0
        else:
            start = _char_index(text, self._end - offset)
        new = text[start:]
        self.holding = not finished and new.endswith("�")
        if self.holding:
            new = new[:-1]
        if new:
            chunks.append(new)
        # Record what is delivered before calling on_log, so a callback that
        # raises can never cause the same text to be delivered twice.
        self._window_offset = offset
        self._chars = len(text) - self.holding
        self._size = size
        self.known_size = size
        if self.holding:
            self._end = min(offset + len(text[: self._chars].encode("utf-8")), size)
        else:
            self._end = size
        for chunk in chunks:
            try:
                self._on_log(chunk)
            except Exception as error:
                raise _LogCallbackError(error) from error


class _LogCallbackError(Exception):
    """Carries an exception raised by the caller's ``on_log`` out of a poll.

    wait() retries failed API calls; wrapping keeps it from mistaking a
    callback's own error for one of those.
    """

    def __init__(self, error: Exception):
        super().__init__(str(error))
        self.error = error


def _char_index(text: str, byte_count: int) -> int:
    """The index of the first character of ``text`` after its first ``byte_count`` UTF-8 bytes."""
    consumed = 0
    for index, char in enumerate(text):
        if consumed >= byte_count:
            return index
        consumed += len(char.encode("utf-8"))
    return len(text)


def _is_transient(error: Exception) -> bool:
    """Whether a failed poll is worth retrying: the build itself is unaffected."""
    if isinstance(error, (CelestoRateLimitError, CelestoNetworkError)):
        return True
    if isinstance(error, CelestoServerError) and not isinstance(
        error, CelestoConflictError
    ):
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", 500)
        return status_code >= 500
    return False


def _retry_delay(error: Exception, poll_interval: float, failed_polls: int) -> float:
    """Exponential backoff from ``poll_interval``, at least the server's Retry-After."""
    # Cap the exponent: past the cap the delay is _MAX_RETRY_BACKOFF anyway,
    # and a huge power of two would overflow a float poll_interval.
    exponent = min(failed_polls - 1, 16)
    backoff = min(poll_interval * 2**exponent, _MAX_RETRY_BACKOFF)
    retry_after = getattr(error, "retry_after", None) or 0
    return max(backoff, retry_after)


def _build_error(data: dict[str, Any]) -> CelestoTemplateBuildError:
    """Describe a finished build that did not end ready."""
    template_id = data.get("id")
    status = data.get("status")
    failure = data.get("failure")
    if not isinstance(failure, dict):
        failure = None
    if status == "needs_rebuild":
        message = f"Template {template_id} needs a rebuild: its base template changed. Call rebuild()."
    else:
        message = f"Template {template_id} build {status}"
        if failure and failure.get("line"):
            message += f" at line {failure.get('line_number')}: {failure['line']!r}"
            if failure.get("exit_code") is not None:
                message += f" (exit code {failure['exit_code']})"
        elif data.get("error"):
            message += f": {data['error']}"
        if failure and failure.get("hint"):
            message += f". Hint: {failure['hint']}"
    return CelestoTemplateBuildError(message, template=data, failure=failure)
