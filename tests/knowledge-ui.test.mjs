import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';
import {knowledgeProposalHTML, knowledgeReferencesHTML, handleKnowledgeProposalAction, renderKnowledge} from '../static/knowledge-ui.js';
import {memoryReceiptHTML, handleMemoryAction} from '../static/memory-ui.js';

test('CSS files isolate workbench dark theme from settings light theme', () => {
  const settingsCss = readFileSync(new URL('../static/settings-ui.css', import.meta.url), 'utf8');
  const memoryCss = readFileSync(new URL('../static/memory.css', import.meta.url), 'utf8');
  const knowledgeCss = readFileSync(new URL('../static/knowledge.css', import.meta.url), 'utf8');
  const indexHtml = readFileSync(new URL('../static/index.html', import.meta.url), 'utf8');

  // Verify stylesheet loading in index.html
  assert.ok(indexHtml.includes('/static/knowledge.css?v=20260929-km'), 'index.html must link knowledge.css statically');
  assert.ok(indexHtml.includes('/static/memory.css?v=20260929-km'), 'index.html must link updated memory.css');

  // Verify settings isolation
  assert.ok(settingsCss.includes('color-scheme:light'), '#settingsView must specify light color-scheme');
  assert.ok(settingsCss.includes('--paper:#f6f7f9'), '#settingsView must scope light --paper');
  assert.ok(settingsCss.includes('--surface:#ffffff'), '#settingsView must scope light --surface');
  assert.ok(settingsCss.includes('--line:#dce2eb'), '#settingsView must scope light --line');
  assert.ok(settingsCss.includes('--ink:#253047'), '#settingsView must scope light --ink');

  // Verify memory.css dark-mode readability: does NOT fall back to raw white #fafaf8
  assert.ok(!memoryCss.includes('background:var(--panel,#fafaf8)'), 'memory-receipt must not use hardcoded light panel fallback');
  assert.ok(memoryCss.includes('background: var(--surface)'), 'memory-receipt must adapt to --surface');
  assert.ok(memoryCss.includes('color: var(--ink)'), 'memory-receipt must adapt to --ink');
  assert.ok(memoryCss.includes('[data-memory-proposal="confirm"]'), 'memory.css must style confirm button');
  assert.ok(memoryCss.includes('[data-memory-proposal="ignore"]'), 'memory.css must style ignore button');

  // Verify knowledge.css styling for all buttons and interactive states
  assert.ok(knowledgeCss.includes('.knowledge-batch button[data-batch="confirm"]'), 'Batch confirm button must be styled');
  assert.ok(knowledgeCss.includes('.knowledge-batch button[data-batch="ignore"]'), 'Batch ignore button must be styled');
  assert.ok(knowledgeCss.includes('.knowledge-members button[data-member]'), 'Member adjust button must be styled');
  assert.ok(knowledgeCss.includes('.knowledge-members button[data-member-add]'), 'Member add button must be styled');
  assert.ok(knowledgeCss.includes('.knowledge-list .settings-list-item.active'), 'Selected item active state must be styled');
  assert.ok(knowledgeCss.includes('@media(max-width: 760px)'), 'Narrow screen responsiveness must be covered');
});

test('chat proposal cards render proper action containers, primary buttons, and link classes', () => {
  // Personal memory proposal card
  const memoryPending = memoryReceiptHTML({
    memory_receipt: {
      saved: false,
      status: 'pending_confirmation',
      proposal_status: 'pending',
      proposal_id: 'mem123',
      proposal_revision: 1,
      item: {content: '偏好条款说明'}
    }
  });
  assert.ok(memoryPending.includes('class="memory-receipt-actions"'), 'Must have action container');
  assert.ok(memoryPending.includes('class="primary"'), 'Confirm button must have primary class');
  assert.ok(memoryPending.includes('data-memory-proposal="confirm"'), 'Must have confirm action');
  assert.ok(memoryPending.includes('data-memory-proposal="ignore"'), 'Must have ignore action');
  assert.ok(memoryPending.includes('class="memory-receipt-link"'), 'Edit link must have memory-receipt-link class');

  // Organization knowledge proposal card
  const orgPending = knowledgeProposalHTML({
    knowledge_proposal: {
      id: 'prop456',
      kind: 'rule',
      status: 'pending',
      proposal_revision: 2,
      can_publish: true,
      content: {title: '付款条件规则'}
    }
  });
  assert.ok(orgPending.includes('class="memory-receipt-actions"'), 'Must have action container');
  assert.ok(orgPending.includes('class="primary"'), 'Publish button must have primary class');
  assert.ok(orgPending.includes('data-knowledge-decision="confirm"'), 'Must have confirm action');
  assert.ok(orgPending.includes('data-knowledge-decision="ignore"'), 'Must have ignore action');
  assert.ok(orgPending.includes('class="memory-receipt-link"'), 'Edit link must have memory-receipt-link class');
});

test('handleMemoryAction and handleKnowledgeProposalAction disable buttons in flight', async () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>');
  const prevDoc = globalThis.document;
  const prevCustomEvent = globalThis.CustomEvent;
  const prevEvent = globalThis.Event;
  const priorFetch = globalThis.fetch;
  let decideResolver;
  const decideGate = new Promise(resolve => { decideResolver = resolve; });

  try {
    globalThis.document = dom.window.document;
    globalThis.CustomEvent = dom.window.CustomEvent;
    globalThis.Event = dom.window.Event;
    globalThis.fetch = async () => {
      await decideGate;
      return {ok: true, json: async () => ({ok: true})};
    };

    // Test memory proposal action
    const memContainer = dom.window.document.createElement('div');
    memContainer.innerHTML = `<aside class="memory-receipt" data-pending-proposal="p1"><button data-memory-proposal="confirm" data-id="p1" data-revision="1">确认</button><button data-memory-proposal="ignore" data-id="p1" data-revision="1">忽略</button></aside>`;
    dom.window.document.body.appendChild(memContainer);
    const confirmBtn = memContainer.querySelector('[data-memory-proposal="confirm"]');
    const ignoreBtn = memContainer.querySelector('[data-memory-proposal="ignore"]');

    const memPromise = handleMemoryAction({target: confirmBtn, preventDefault: () => {}});
    assert.equal(confirmBtn.disabled, true, 'Confirm button must be disabled in flight');
    assert.equal(ignoreBtn.disabled, true, 'Ignore button must be disabled in flight');

    decideResolver();
    await memPromise;
    assert.ok(memContainer.innerHTML.includes('提案已处理'));

    // Test knowledge proposal action
    let orgResolver;
    const orgGate = new Promise(resolve => { orgResolver = resolve; });
    globalThis.fetch = async () => {
      await orgGate;
      return {ok: true, json: async () => ({ok: true})};
    };

    const orgContainer = dom.window.document.createElement('div');
    orgContainer.innerHTML = `<aside class="memory-receipt knowledge-proposal" data-knowledge-chat-proposal="k1"><button data-knowledge-decision="confirm" data-id="k1" data-revision="1">发布</button><button data-knowledge-decision="ignore" data-id="k1" data-revision="1">忽略</button></aside>`;
    dom.window.document.body.appendChild(orgContainer);
    const pubBtn = orgContainer.querySelector('[data-knowledge-decision="confirm"]');
    const ignBtn = orgContainer.querySelector('[data-knowledge-decision="ignore"]');

    const orgPromise = handleKnowledgeProposalAction({target: pubBtn, preventDefault: () => {}});
    assert.equal(pubBtn.disabled, true, 'Publish button must be disabled in flight');
    assert.equal(ignBtn.disabled, true, 'Ignore button must be disabled in flight');

    orgResolver();
    await orgPromise;
    assert.ok(orgContainer.innerHTML.includes('提案已处理'));
  } finally {
    globalThis.document = prevDoc;
    globalThis.CustomEvent = prevCustomEvent;
    globalThis.Event = prevEvent;
    globalThis.fetch = priorFetch;
  }
});

test('renderKnowledge renders list with selection state and proposals inbox', async () => {
  const dom = new JSDOM('<!doctype html><html><body><div id="settingsPage"></div></body></html>');
  const prevDoc = globalThis.document;
  const prevSession = globalThis.sessionStorage;
  const prevFetch = globalThis.fetch;

  try {
    globalThis.document = dom.window.document;
    globalThis.sessionStorage = {getItem: () => null};
    globalThis.fetch = async (url) => {
      const u = String(url);
      if (u.includes('/api/knowledge/profile')) return {ok: true, json: async () => ({active: true, role: 'maintainer'})};
      if (u.includes('/api/knowledge/items')) {
        return {
          ok: true,
          json: async () => ({
            items: [
              {id: 'item1', title: '关于违约金上限', content: '违约金上限通常设定为总金额的20%', status: 'active', revision: 1},
              {id: 'item2', title: '付款账期约定', content: '约定收到发票后30天内支付', status: 'inactive', revision: 2}
            ]
          })
        };
      }
      if (u.includes('/api/knowledge/proposals')) {
        return {
          ok: true,
          json: async () => ({
            items: [
              {id: 'prop1', kind: 'rule', action: 'create', proposal_revision: 1, owner_id: 'user1', content: {title: '新违约金标准'}}
            ]
          })
        };
      }
      if (u.includes('/api/knowledge/members')) {
        return {
          ok: true,
          json: async () => [
            {user_id: 'u1', username: 'alice', active: 1, role: 'maintainer'},
            {user_id: 'u2', username: 'bob', active: 1, role: 'member'}
          ]
        };
      }
      if (u.includes('/api/knowledge/parties')) return {ok: true, json: async () => ({items: []})};
      if (u.includes('/api/knowledge/imports')) return {ok: true, json: async () => []};
      return {ok: true, json: async () => ({})};
    };

    const root = dom.window.document.getElementById('settingsPage');
    await renderKnowledge(root, {identity: {id: 'user1', role: 'admin'}});

    // Verify toolbar and batch buttons
    assert.ok(root.querySelector('[data-new]').classList.contains('primary'), 'New knowledge button must be primary');
    assert.ok(root.querySelector('[data-batch="confirm"]'), 'Batch confirm button must exist');
    assert.ok(root.querySelector('[data-batch="ignore"]'), 'Batch ignore button must exist');

    // Verify proposals rendered
    assert.ok(root.querySelector('[data-proposal="prop1"]'), 'Proposal prop1 must be rendered');
    assert.ok(root.querySelector('[data-proposal-check]'), 'Proposal checkbox must be rendered');

    // Verify list items and selection toggle
    const listItems = root.querySelectorAll('[data-item]');
    assert.equal(listItems.length, 2, 'Two knowledge items should be rendered');
    assert.equal(listItems[0].classList.contains('active'), false);

    // Simulate clicking an item
    globalThis.fetch = async (url) => {
      if (String(url).includes('/versions')) return {ok: true, json: async () => [{revision: 1, status: 'active'}]};
      return {ok: true, json: async () => ({id: 'item1', scope: 'personal', kind: 'preference', title: '关于违约金上限', content: '违约金上限通常设定为总金额的20%', status: 'active', revision: 1})};
    };
    await listItems[0].onclick();
    assert.equal(listItems[0].classList.contains('active'), true, 'Clicked item must have active class');
    assert.equal(listItems[1].classList.contains('active'), false, 'Unclicked item must not have active class');

    // Verify detail rendered
    const detail = root.querySelector('.knowledge-detail');
    assert.ok(detail.innerHTML.includes('关于违约金上限'), 'Detail must show item title');
    assert.ok(detail.querySelector('[data-edit]'), 'Detail must have edit button');
    assert.ok(detail.querySelector('[data-disable]'), 'Active item must have disable button');

    // Verify members section
    const membersSec = root.querySelector('.knowledge-members');
    assert.ok(membersSec, 'Members section must be rendered for admin');
    assert.ok(membersSec.querySelector('[data-member-add]'), 'Add member button must exist');
    assert.ok(membersSec.querySelector('[data-member]'), 'Member adjust button must exist');
  } finally {
    globalThis.document = prevDoc;
    globalThis.sessionStorage = prevSession;
    globalThis.fetch = prevFetch;
  }
});
