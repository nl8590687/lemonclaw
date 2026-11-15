[Documentation](index.md) · [简体中文](../zh/interaction.md)

# Notifications and human confirmation

## Key notifications

The main agent normally sends a final reply and may report important milestones or blockers. An already delivered result need not be repeated; background events requiring no attention may complete silently. User messages and scheduled tasks cannot suppress a reply solely on that basis.

## Answer a confirmation

For critical decisions or missing information, the agent can ask single-choice, multiple-choice, or text questions.

- Terminal: enter `1` for a single choice, `1,2` for multiple choices, or `0:Actual answer` for an alternative. Multiple text fields can use `1:Name,2:Age`.
- Feishu: use the card's dropdowns, text inputs, and confirm/cancel buttons.
- `/question`: redisplay/resend the current question in the original channel without extending its deadline.
- `/cancel`: cancel the question.
- `/clear`: clear the session and invalidate old questions.

Only the original channel/requesting user can answer. The default timeout is one hour, with allowed limits of 20 minutes to 24 hours. Cancellation or timeout does not guess an answer; associated workflows remain paused. Waiting survives restart, and offline time counts toward the deadline.

## Feishu configuration

Enable `card.action.trigger` callbacks through the existing long connection. Without callbacks, answer or cancel using text in the original chat; resend a missing card with `/question`. Full console screenshots remain to be added.

## Session recovery

An interrupted turn can resume from saved state on subsequent input. Some tools may execute again during recovery; external writes should be idempotent. Terminal and Feishu share the personal main session by default; separate entry points do not imply isolated sessions.
