from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str
    created_at: datetime


class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=200)


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=72)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class BookOut(ORM):
    id: int
    title: str
    author: str | None
    description: str | None
    language: str | None
    status: str
    progress: float
    chunks: int
    pages: int | None
    error: str | None
    is_published: bool
    has_cover: bool
    file_name: str
    file_size: int
    created_at: datetime
    updated_at: datetime
    suggested_questions: list[str]


class BookPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    author: str | None = None
    description: str | None = None
    is_published: bool | None = None
    suggested_questions: list[str] | None = None


class ConversationCreate(BaseModel):
    book_id: int


class MessageOut(ORM):
    id: int
    role: str
    content: str
    citations: list
    provider: str | None
    created_at: datetime


class ConversationOut(ORM):
    id: int
    book_id: int
    book_title: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    speak: bool = True
    voice: str | None = None
    style: Literal["concise", "detailed"] = "concise"


class TTS(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    voice: str | None = None
