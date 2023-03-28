"""The slides bot."""
from __future__ import annotations

from asyncio import Queue, TaskGroup, sleep
from itertools import count
from typing import TYPE_CHECKING, Any, Callable, Literal, Protocol, TypeVar

from aiohttp import ClientWebSocketResponse
from cattrs.preconf.json import make_converter

from ._unions import configure_tagged_union  # type: ignore
from .models import (
    ChannelEvent,
    ChannelRequest,
    ChatEvent,
    EmoteEvent,
    Error,
    GetRoomUsersRequest,
    GetRoomUsersResponse,
    IndicatorRequest,
    Item,
    Position,
    SessionMetadata,
    TeleportRequest,
    TipReactionEvent,
    User,
    UserJoinedEvent,
    UserLeftEvent,
)

if TYPE_CHECKING:
    from attrs import AttrsInstance
else:

    class AttrsInstance(Protocol):
        pass


__all__ = ["BaseBot", "Highrise", "User", "Position"]
A = TypeVar("A", bound=AttrsInstance)
T = TypeVar("T")


class BaseBot:
    """A base class for Highrise bots.
    Bots join a room and interact with everything in it.

    Subclass this class and implement the handlers you want to use.

    The `self.highrise` attribute can be used to make requests.
    """

    highrise: Highrise

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        """On a connection to the room being established.

        This may be called multiple times, since the connection may be dropped
        and reestablished.
        """
        pass

    async def on_chat(self, user: User, message: str) -> None:
        """On a received room-wide chat."""
        pass

    async def on_whisper(self, user: User, message: str) -> None:
        """On a received room whisper."""
        pass

    async def on_emote(self, user: User, emote_id: str, receiver: User | None) -> None:
        """On a received emote."""
        pass

    async def on_user_join(self, user: User) -> None:
        """On a user joining the room."""
        pass

    async def on_tip(self, sender: User, receiver: User, tip: Item) -> None:
        """On a tip received in the room."""
        pass

    async def on_channel(self, message: str, tags: set[str]) -> None:
        """On a hidden channel message."""
        pass


class Highrise:
    ws: ClientWebSocketResponse
    tg: TaskGroup
    _req_id = count()
    _req_id_registry: dict[str, Queue[Any]] = {}

    async def chat(self, message: str) -> None:
        """Broadcast a room-wide chat message."""
        await self.ws.send_json({"_type": "ChatRequest", "message": message})

    async def send_whisper(self, user_id: str, message: str) -> None:
        await self.ws.send_json(
            {"_type": "ChatRequest", "message": message, "whisper_target_id": user_id}
        )

    async def send_emote(
        self, emote_id: str, target_user_id: str | None = None
    ) -> None:
        payload = {"_type": "EmoteRequest", "emote_id": emote_id}
        if target_user_id is not None:
            payload["target_user_id"] = target_user_id
        await self.ws.send_json(payload)

    async def set_indicator(
        self, icon: str | None
    ) -> IndicatorRequest.Response | Error:
        return await do_req_resp(self, IndicatorRequest(icon))

    async def send_channel(
        self, message: str, tags: set[str] = set()
    ) -> ChannelRequest.ChannelResponse | Error:
        return await do_req_resp(self, ChannelRequest(message, tags))

    async def walk_to(
        self,
        dest: tuple[float, float, float],
        facing: Literal["FrontRight", "FrontLeft", "BackRight", "BackLeft"],
    ) -> None:
        await self.ws.send_json(
            {"_type": "FloorHitRequest", "destination": dest, "facing": facing}
        )

    async def teleport(
        self, user_id: str, dest: Position
    ) -> TeleportRequest.TeleportResponse | Error:
        return await do_req_resp(self, TeleportRequest(user_id, dest))

    async def get_room_users(self) -> list[tuple[User, Position]]:
        req_id = str(next(self._req_id))
        self._req_id_registry[req_id] = (q := Queue[Any](maxsize=1))
        await self.ws.send_str(
            converter.dumps(GetRoomUsersRequest(str(req_id)), Outgoing)
        )
        return await q.get()

    def call_in(self, callback: Callable, delay: float) -> None:
        self.tg.create_task(_delayed_callback(callback, delay))


class _ClassWithId(AttrsInstance):
    rid: str | None


CID = TypeVar("CID", bound=_ClassWithId, covariant=True)


class _ReqWithId(AttrsInstance, Protocol[CID]):
    rid: str | None

    @property
    def Response(self) -> type[CID]:
        ...


async def do_req_resp(hr: Highrise, req: _ReqWithId[CID]) -> CID | Error:
    rid = str(next(hr._req_id))
    req.rid = rid
    hr._req_id_registry[rid] = (q := Queue[Any](maxsize=1))
    await hr.ws.send_str(converter.dumps(req, Outgoing))
    return await q.get()


async def _delayed_callback(callback: Callable, delay: float) -> None:
    await sleep(delay)
    await callback()


converter = make_converter()

Incoming = (
    Error
    | GetRoomUsersResponse
    | ChatEvent
    | EmoteEvent
    | UserJoinedEvent
    | UserLeftEvent
    | ChannelEvent
    | TipReactionEvent
    | IndicatorRequest.IndicatorResponse
    | ChannelRequest.ChannelResponse
    | TeleportRequest.TeleportResponse
)
Outgoing = (
    ChatEvent
    | ChannelEvent
    | GetRoomUsersRequest
    | IndicatorRequest
    | ChannelRequest
    | TeleportRequest
)
configure_tagged_union(SessionMetadata | Error, converter)
configure_tagged_union(Incoming, converter)
configure_tagged_union(Outgoing, converter)