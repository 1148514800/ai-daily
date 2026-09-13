import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isSummaryOnly, languageLabel, parseArticleBody } from './articleBody.ts';

test('parseArticleBody returns nothing for an empty body', () => {
  assert.deepEqual(parseArticleBody(''), []);
  assert.deepEqual(parseArticleBody(null), []);
  assert.deepEqual(parseArticleBody('   \n\n  '), []);
});

test('parseArticleBody keeps paragraphs as separate blocks', () => {
  const blocks = parseArticleBody('First paragraph.\n\nSecond paragraph.');
  assert.deepEqual(blocks, [
    { kind: 'paragraph', text: 'First paragraph.' },
    { kind: 'paragraph', text: 'Second paragraph.' },
  ]);
});

test('parseArticleBody recognises headings, lists and quotes', () => {
  const blocks = parseArticleBody('## Section\n\n- item one\n\n> quoted line');
  assert.deepEqual(blocks, [
    { kind: 'heading', level: 2, text: 'Section' },
    { kind: 'list', text: 'item one' },
    { kind: 'quote', text: 'quoted line' },
  ]);
});

test('parseArticleBody collapses intra-paragraph whitespace only', () => {
  const [block] = parseArticleBody('A line\nthat wrapped in the source.');
  assert.equal(block.kind, 'paragraph');
  assert.equal(block.text, 'A line that wrapped in the source.');
});

test('parseArticleBody leaves English text in English', () => {
  const [block] = parseArticleBody('OpenAI introduced a new reasoning mode today.');
  assert.equal(block.text, 'OpenAI introduced a new reasoning mode today.');
});

test('parseArticleBody leaves Chinese text in Chinese', () => {
  const [block] = parseArticleBody('OpenAI 今天发布了新的推理模式。');
  assert.equal(block.text, 'OpenAI 今天发布了新的推理模式。');
});

test('languageLabel names the languages the backend produces', () => {
  assert.equal(languageLabel('en'), '英文原文');
  assert.equal(languageLabel('zh'), '中文原文');
  assert.equal(languageLabel('ja'), '日文原文');
  assert.equal(languageLabel(''), '原文');
  assert.equal(languageLabel(null), '原文');
});

test('isSummaryOnly flags bodies that are only the feed summary', () => {
  assert.equal(isSummaryOnly('rss_summary'), true);
  assert.equal(isSummaryOnly(''), true);
  assert.equal(isSummaryOnly(null), true);
  assert.equal(isSummaryOnly('web'), false);
  assert.equal(isSummaryOnly('rss_full'), false);
});
