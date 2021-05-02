import logging
import sys
from typing import Optional, Tuple

from github import Github
from pydantic import BaseModel, BaseSettings, SecretStr, FilePath, ValidationError


class Settings(BaseSettings):
    github_repository: str
    github_event_path: FilePath
    github_event_name: Optional[str] = None
    input_token: SecretStr
    reviewers: Tuple[str, ...] = ('samuelcolvin',)
    request_update_trigger: str = 'please update'
    request_review_trigger: str = 'please review'
    awaiting_update_label: str = 'awaiting author updates'
    awaiting_review_label: str = 'awaiting review'


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

try:
    s = Settings()
except ValidationError as e:
    logging.error('error loading Settings\n:%s', e)
    sys.exit(1)

contents = s.github_event_path.read_text()
event = GitHubEvent.parse_raw(contents)

if event.issue.pull_request is None:
    logging.info('action only applies to pull requests, not issues')
    sys.exit(0)

body = event.comment.body.lower()

g = Github(s.input_token.get_secret_value())
repo = g.get_repo(s.github_repository)
pr = repo.get_pull(event.issue.number)
commenter_is_reviewer = event.comment.user.login not in s.reviewers
commenter_is_author = event.issue.user.login == event.comment.user.login


def remove_label(label: str):
    labels = pr.get_labels()
    if any(lb.name == label for lb in labels):
        pr.remove_from_labels(label)


def assigned_author() -> Tuple[bool, str]:
    if commenter_is_reviewer:
        return False, f'Only reviews {s.reviewers} can re-assign the author, not {event.comment.user.login}'
    pr.add_to_labels(s.awaiting_update_label)
    remove_label(s.awaiting_review_label)
    pr.add_to_assignees(event.issue.user.login)
    to_remove = [r for r in s.reviewers if r != event.issue.user.login]
    if to_remove:
        pr.remove_from_assignees(*to_remove)
    return True, f'author {event.issue.user.login} successfully assigned to PR, "{s.awaiting_update_label}" label added'


def request_review() -> Tuple[bool, str]:
    if not (commenter_is_reviewer or commenter_is_author):
        return False, (
            f'Only the PR author {event.issue.user.login} or reviews can request a review, '
            f'not {event.comment.user.login}'
        )
    pr.add_to_labels(s.awaiting_review_label)
    remove_label(s.awaiting_update_label)
    pr.add_to_assignees(*s.reviewers)
    if event.issue.user.login not in s.reviewers:
        pr.remove_from_assignees(event.issue.user.login)
    return True, f'reviews {s.reviewers} successfully assigned to PR, "{s.awaiting_review_label}" label added'


if s.request_update_trigger in body:
    success, msg = assigned_author()
elif s.request_review_trigger in body:
    success, msg = request_review()
else:
    success = True
    msg = (
        f'neither {s.request_update_trigger!r} nor {s.request_review_trigger!r} found in comment body, not proceeding'
    )

if success:
    logging.info('success: %s', msg)
else:
    logging.warning('warning: %s', msg)
    sys.exit(1)
