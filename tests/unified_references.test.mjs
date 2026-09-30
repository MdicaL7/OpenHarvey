import test from 'node:test';
import assert from 'node:assert/strict';
import {sourceReferencesHTML} from '../static/materials-ui.js';
import {conversationHTML} from '../static/ui-utils.js';
import {setLanguage} from '../static/i18n.js';

test('unified references: only contract sources', () => {
  setLanguage('zh-CN');
  const docs = [
    {id: '111111111111', filename: '服务采购协议.docx', source_hash: 'h1', locations: {B1: {ordinal: 1}, B2: {ordinal: 2}}},
  ];
  const text = '根据【D111111111111:B1】与【D111111111111:B2】的约定。';
  const html = sourceReferencesHTML(text, docs, {materialsEnabled: true});
  assert.match(html, /引用来源 · 1/);
  assert.match(html, /服务采购协议\.docx/);
  assert.match(html, /data-block="B1"/);
  assert.match(html, /data-block="B2"/);
  assert.match(html, /class="reference-tag reference-tag-contract"/);
});

test('unified references: only personal preferences', () => {
  setLanguage('zh-CN');
  const pref = {
    id: 'pref00000001',
    content: '请使用专业严谨、精炼简洁的中文表达',
    revision: 1,
    current_revision: 1,
    current_status: 'active',
    kind: 'preference',
    scope: 'personal',
  };
  const html = sourceReferencesHTML('这是回答', [], {
    memoryReferences: [pref],
    materialsEnabled: false, // Must not depend on materials_enabled
  });
  assert.match(html, /引用来源 · 1/);
  assert.match(html, /表达偏好/);
  assert.match(html, /请使用专业严谨/);
  assert.match(html, /· v1/);
  assert.match(html, /data-reference-type="preference"/);
});

test('unified references: only organization knowledge with 3 kinds', () => {
  setLanguage('zh-CN');
  const rule = {
    item_id: 'rule00000001',
    title: '知识产权与保密审查基线',
    revision: 1,
    current_revision: 1,
    current_status: 'active',
    kind: 'rule',
    scope: 'organization',
  };
  const template = {
    item_id: 'tmpl00000001',
    title: '技术开发标准合同范本2026',
    revision: 2,
    current_revision: 2,
    current_status: 'active',
    kind: 'template',
    scope: 'organization',
  };
  const caseItem = {
    item_id: 'case00000001',
    title: '某供应商履约违约处置先例',
    revision: 1,
    current_revision: 1,
    current_status: 'active',
    kind: 'case',
    scope: 'organization',
  };
  const html = sourceReferencesHTML('分析结论', [], {
    knowledgeReferences: [rule, template, caseItem],
    materialsEnabled: false,
  });
  assert.match(html, /引用来源 · 3/);
  assert.match(html, /审查标准/);
  assert.match(html, /知识产权与保密审查基线/);
  assert.match(html, /参考范本/);
  assert.match(html, /技术开发标准合同范本2026/);
  assert.match(html, /案例与决策/);
  assert.match(html, /某供应商履约违约处置先例/);
});

test('unified references: mixed sources aggregation and deduplication', () => {
  setLanguage('zh-CN');
  const docs = [
    {id: '111111111111', filename: '主合同.docx', primary: true, locations: {B10: {ordinal: 10}, B12: {ordinal: 12}}},
    {id: '222222222222', filename: '附件一.pdf', thread_id: 't1', locations: {B1: {ordinal: 1}}},
  ];
  const text = '合同明确【D111111111111:B10】以及【D111111111111:B12】，附件要求【D222222222222:B1】';
  const pref = {
    id: 'p1',
    content: '偏好要点',
    revision: 1,
    current_revision: 1,
    current_status: 'active',
    kind: 'preference',
  };
  const rule = {
    item_id: 'r1',
    title: '付款账期基线',
    revision: 1,
    current_revision: 1,
    current_status: 'active',
    kind: 'rule',
  };

  // Duplicate pref and rule should be deduplicated
  const html = sourceReferencesHTML(text, docs, {
    memoryReferences: [pref, {...pref}],
    knowledgeReferences: [rule, {...rule}],
    materialsEnabled: true,
  });
  // 2 documents + 1 pref + 1 rule = 4 sources
  assert.match(html, /引用来源 · 4/);
  assert.match(html, /主合同/);
  assert.match(html, /附件/);
  assert.match(html, /表达偏好/);
  assert.match(html, /审查标准/);
});

test('unified references: different revisions preserved, inactive/updated status annotated', () => {
  setLanguage('zh-CN');
  const oldRev = {
    item_id: 'r1',
    title: '旧版审查标准',
    revision: 1,
    current_revision: 2, // updated
    current_status: 'active',
    kind: 'rule',
  };
  const newRev = {
    item_id: 'r1',
    title: '新版审查标准',
    revision: 2,
    current_revision: 2,
    current_status: 'active',
    kind: 'rule',
  };
  const inactivePref = {
    id: 'p1',
    content: '已停用的偏好',
    revision: 1,
    current_revision: 1,
    current_status: 'inactive', // disabled
    kind: 'preference',
  };
  const html = sourceReferencesHTML('分析', [], {
    memoryReferences: [inactivePref],
    knowledgeReferences: [oldRev, newRev],
    materialsEnabled: false,
  });
  // Both revisions preserved -> 2 knowledge + 1 memory = 3
  assert.match(html, /引用来源 · 3/);
  assert.match(html, /已有新版本/);
  assert.match(html, /已停用/);
});

test('unified references: empty when no valid citations exist', () => {
  assert.equal(sourceReferencesHTML('没有引用', [], {memoryReferences: [], knowledgeReferences: []}), '');
  assert.equal(sourceReferencesHTML('伪造引用【D000000000000:B1】', [], {memoryReferences: [], knowledgeReferences: []}), '');
});

test('conversationHTML: aggregates consecutive assistant messages into one unified sources section at the end', () => {
  setLanguage('zh-CN');
  const docs = [
    {id: '111111111111', filename: '主合同.docx', primary: true, locations: {B1: {ordinal: 1}}},
  ];
  const pref = {
    id: 'p1',
    content: '偏好设置',
    revision: 1,
    current_revision: 1,
    current_status: 'active',
    kind: 'preference',
  };
  const rule = {
    item_id: 'r1',
    title: '通用规则',
    revision: 1,
    current_revision: 1,
    current_status: 'active',
    kind: 'rule',
  };

  const state = {
    materials_enabled: true,
    documents: docs,
    status: {type: 'idle'},
    messages: [
      {
        info: {id: 'user_1', role: 'user'},
        parts: [{type: 'text', text: '请审查合同'}],
      },
      // Assistant message 1: tool execution
      {
        info: {id: 'asst_1', role: 'assistant'},
        parts: [
          {
            type: 'tool',
            tool: 'read',
            state: {status: 'completed', input: {path: 'contract.txt'}, output: 'clause text'},
          },
        ],
      },
      // Assistant message 2: final answer citing document, memory and knowledge
      {
        info: {id: 'asst_2', role: 'assistant', time: {completed: 1}},
        parts: [
          {
            type: 'text',
            text: '审查结论见【D111111111111:B1】。',
            memory_references: [pref],
            knowledge_references: [rule],
          },
        ],
      },
    ],
  };

  const html = conversationHTML(state, new Set());
  // Count how many "引用来源" disclosures appear
  const matches = html.match(/引用来源 · \d+/g);
  assert.equal(matches?.length, 1, 'Only one 引用来源 disclosure should appear for the assistant turn');
  assert.match(html, /引用来源 · 3/); // 1 doc + 1 pref + 1 rule = 3

  // Tool card should appear before the references disclosure
  const toolIndex = html.indexOf('bui-tool');
  const refIndex = html.indexOf('material-references');
  assert.ok(toolIndex >= 0 && refIndex > toolIndex, 'References must appear at the end of the assistant turn after tools');
});

test('conversationHTML: preserves open state across renders via data-key', () => {
  setLanguage('zh-CN');
  const pref = {
    id: 'p1',
    content: '偏好设置',
    revision: 1,
    current_revision: 1,
    current_status: 'active',
    kind: 'preference',
  };
  const state = {
    materials_enabled: false,
    documents: [],
    status: {type: 'idle'},
    messages: [
      {
        info: {id: 'asst_1', role: 'assistant', time: {completed: 1}},
        parts: [{type: 'text', text: '已参考偏好', memory_references: [pref]}],
      },
    ],
  };

  // Initially closed
  const closedHTML = conversationHTML(state, new Set());
  assert.match(closedHTML, /data-key="sources-asst_1"/);
  assert.doesNotMatch(closedHTML, /<details[^>]+open/);

  // Opened by user
  const openSet = new Set(['sources-asst_1']);
  const openedHTML = conversationHTML(state, openSet);
  assert.match(openedHTML, /<details class="material-references" data-key="sources-asst_1" open>/);
});
