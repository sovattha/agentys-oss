import { describe, it, expect } from 'vitest';
import { buildReplyAllRecipients, pickReplyRecipient } from './replyRecipient';

describe('pickReplyRecipient', () => {
  it('returns sender for a normal inbound email', () => {
    expect(
      pickReplyRecipient('alice@x.com', ['me@gmail.com'], 'me@gmail.com'),
    ).toBe('alice@x.com');
  });

  it('returns email.to[0] when sender is the user (self-sent email)', () => {
    // User sent to alice; reply should go to alice, not to themselves.
    expect(
      pickReplyRecipient('me@gmail.com', ['alice@x.com'], 'me@gmail.com'),
    ).toBe('alice@x.com');
  });

  it('exact bug repro: self-only thread (Re: Confirmer présence demain)', () => {
    // User sent the latest reply; "Moi" is the sender.
    expect(
      pickReplyRecipient(
        'cours.universite@gmail.com',
        ['bob@example.com'],
        'cours.universite@gmail.com',
      ),
    ).toBe('bob@example.com');
  });

  it('skips the user when they also appear in original To: (cc-self pattern)', () => {
    expect(
      pickReplyRecipient(
        'me@gmail.com',
        ['me@gmail.com', 'alice@x.com'],
        'me@gmail.com',
      ),
    ).toBe('alice@x.com');
  });

  it('falls back to to[0] when only the user is in To:', () => {
    // Edge case: user sent to themselves only. Nothing better to suggest.
    expect(
      pickReplyRecipient('me@gmail.com', ['me@gmail.com'], 'me@gmail.com'),
    ).toBe('me@gmail.com');
  });

  it('returns sender when ownEmail is unknown', () => {
    expect(
      pickReplyRecipient('alice@x.com', ['me@gmail.com'], null),
    ).toBe('alice@x.com');
  });

  it('returns sender when email.to is missing', () => {
    expect(
      pickReplyRecipient('me@gmail.com', undefined, 'me@gmail.com'),
    ).toBe('me@gmail.com');
  });

  it('is case-insensitive on the user email', () => {
    expect(
      pickReplyRecipient(
        'Me@Gmail.com',
        ['alice@x.com'],
        'me@gmail.com',
      ),
    ).toBe('alice@x.com');
  });

  it('matches when sender contains a display name with the user email', () => {
    expect(
      pickReplyRecipient(
        '"Me" <me@gmail.com>',
        ['alice@x.com'],
        'me@gmail.com',
      ),
    ).toBe('alice@x.com');
  });
});

describe('buildReplyAllRecipients', () => {
  it('includes sender and other To recipients, excluding the current account', () => {
    expect(buildReplyAllRecipients({
      sender: 'Marco Bardot <bardot84@gmail.com>',
      to: [
        'laurentmarlyse.jourdan@bluewin.ch',
        'simon.yannick@bluewin.ch',
        'lambert.1996@gmail.com',
      ],
      cc: [],
    }, 'laurentmarlyse.jourdan@bluewin.ch')).toEqual({
      to: [
        'Marco Bardot <bardot84@gmail.com>',
        'simon.yannick@bluewin.ch',
        'lambert.1996@gmail.com',
      ],
      cc: [],
    });
  });

  it('keeps original Cc recipients in Cc and deduplicates addresses', () => {
    expect(buildReplyAllRecipients({
      sender: 'marco@example.com',
      to: ['me@example.com', 'team@example.com'],
      cc: ['Team <team@example.com>', 'ops@example.com', 'me@example.com'],
    }, 'Me <me@example.com>')).toEqual({
      to: ['marco@example.com', 'team@example.com'],
      cc: ['ops@example.com'],
    });
  });

  it('falls back to the original To recipient for self-sent messages', () => {
    expect(buildReplyAllRecipients({
      sender: 'me@example.com',
      to: ['alice@example.com'],
      cc: ['bob@example.com'],
    }, 'me@example.com')).toEqual({
      to: ['alice@example.com'],
      cc: ['bob@example.com'],
    });
  });
});
