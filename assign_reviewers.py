import logging
import sys
from typing import Optional, Literal

from github import Github
from pydantic import BaseModel, BaseSettings, SecretStr, FilePath


class Settings(BaseSettings):
    github_repository: str
    github_event_path: FilePath
    github_event_name: Optional[str] = None
    input_token: SecretStr


class User(BaseModel):
    login: str


class Comment(BaseModel):
    body: str
    user: User


class PullRequest(BaseModel):
    url: str


class Issue(BaseModel):
    pull_request: Optional[PullRequest] = None
    user: User
    number: int


class GitHubEvent(BaseModel):
    comment: Comment
    issue: Issue


logging.basicConfig(level=logging.INFO)

settings = Settings()

contents = settings.github_event_path.read_text()
event = GitHubEvent.parse_raw(contents)

if event.issue.pull_request is None:
    logging.info('action only applies to pull requests, not issues')
    sys.exit(0)

body = event.comment.body.lower()

assigned_author_trigger = 'assign author'
request_review_trigger = 'request review'

g = Github(settings.input_token.get_secret_value())
repo = g.get_repo(settings.github_repository)
pr = repo.get_pull(event.issue.number)
reviewers = ('samuelcolvin',)
awaiting_author_label = 'awaiting author revision'
awaiting_review_label = 'awaiting review'


def remove_label(label: str):
    labels = pr.get_labels()
    if any(lb.name == label for lb in labels):
        pr.remove_from_labels(label)


def assigned_author() -> Optional[str]:
    if event.comment.user.login in reviewers:
        return f'Only reviews {reviewers} can re-assign the author, not {event.comment.user.login}'
    pr.add_to_labels(awaiting_author_label)
    remove_label(awaiting_review_label)
    pr.add_to_assignees(event.issue.user.login)
    to_remove = [r for r in reviewers if r != event.issue.user.login]
    if to_remove:
        pr.remove_from_assignees(*to_remove)
    logging.info(
        'author %s successfully assigned to PR and "%s" label added', event.issue.user.login, awaiting_author_label
    )


def request_review() -> Optional[str]:
    if event.issue.user.login != event.comment.user.login:
        return f'Only the PR author {event.issue.user.login} can request a review, not {event.comment.user.login}'
    pr.add_to_labels(awaiting_review_label)
    remove_label(awaiting_author_label)
    pr.add_to_assignees(*reviewers)
    if event.issue.user.login not in reviewers:
        pr.remove_from_assignees(event.issue.user.login)
    logging.info(
        'reviews %s successfully assigned to PR and "%s" label added', reviewers, awaiting_review_label
    )


if assigned_author_trigger in body:
    err = assigned_author()
elif request_review_trigger in body:
    err = request_review()
else:
    logging.info(
        'neither %r nor %r found in comment body, not proceeding',
        assigned_author_trigger,
        request_review_trigger,
    )
    sys.exit(0)

if err:
    logging.warning('%s', err)
    sys.exit(1)
