"""Public ``Template`` resource: build computers with your own packages preinstalled."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, MutableMapping
from typing import Any

from .computer import Computer, _make_client
from .exceptions import CelestoTemplateBuildError, CelestoValidationError

# Statuses that mean a build is still on its way to ready or failed.
_BUILDING_STATUSES = frozenset({"queued", "building"})


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
        timeout: float = 1800,
        poll_interval: float = 3,
        on_log: Callable[[str], None] | None = None,
    ) -> Template:
        """Block until the build is ready.

        Args:
            timeout: Seconds to wait. Builds are capped at 30 minutes, plus
                time queued, so the default suits most builds.
            poll_interval: Seconds between status checks.
            on_log: Called with each new chunk of build log text as it arrives.

        Returns:
            This template, refreshed, with ``status`` ``ready``.

        Raises:
            CelestoTemplateBuildError: The build failed or needs a rebuild.
                ``failure`` says which script line failed, when known.
            TimeoutError: The build was still running after ``timeout``.
        """
        deadline = time.monotonic() + timeout
        # Byte position in the whole log up to which on_log has been fed, so
        # each poll only hands over text it has not seen yet.
        log_end = 0
        known_size: int | None = None
        while True:
            self.refresh()
            status = self._data.get("status")
            if on_log is not None:
                log_end, known_size = self._follow_log(on_log, log_end, known_size)
            if status == "ready":
                return self
            if status not in _BUILDING_STATUSES:
                raise _build_error(self._data)
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Template {self._identifier()} was still {status} after {timeout:g}s."
                )
            time.sleep(poll_interval)

    def _follow_log(
        self,
        on_log: Callable[[str], None],
        log_end: int,
        known_size: int | None,
    ) -> tuple[int, int | None]:
        """Pass on_log the log text past ``log_end`` and return the new position."""
        response = self.logs(known_size=known_size)
        if response.get("unchanged"):
            return log_end, known_size
        text = response.get("log") or ""
        offset = int(response.get("offset") or 0)
        # The API returns the last 256 KB starting at ``offset``. Skip the
        # part already delivered; if the window has moved past log_end, the
        # bytes in between were cut and only the window can be delivered.
        # Offsets count bytes, so slice the encoded text, not characters.
        raw = text.encode("utf-8")
        new = raw[max(log_end - offset, 0) :]
        if new:
            on_log(new.decode("utf-8", errors="replace"))
        return offset + len(raw), response.get("size")

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
        """Rebuild with the current script and the latest base. Follow it with ``wait()``."""
        self._data = self._client.templates.rebuild(self._identifier())
        return self

    def delete(self) -> None:
        """Delete this template. Computers already created from it keep running."""
        self._client.templates.delete(self._identifier())

    def create_computer(self, **kwargs: Any) -> Computer:
        """Create a computer from this template.

        Takes the same keyword arguments as ``Computer(...)`` except
        ``template_id``. The computer shares this template's API client.
        """
        if "template_id" in kwargs:
            raise CelestoValidationError(
                "create_computer() uses this template's ID; don't pass template_id."
            )
        kwargs.setdefault("client", self._client)
        return Computer(template_id=self._identifier(), **kwargs)

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


def _build_error(data: dict[str, Any]) -> CelestoTemplateBuildError:
    """Describe a finished build that did not end ready."""
    template_id = data.get("id")
    status = data.get("status")
    failure = data.get("failure")
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
