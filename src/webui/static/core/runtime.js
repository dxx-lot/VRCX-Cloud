/* Framework boundary: account context, resource registry, request coalescing,
 * page lifecycle and task cancellation. No feature-specific DOM lives here. */
(function (root, factory) {
  const api = factory(typeof module === 'object' && module.exports ? require('./feed.js') : root.VRCXFeed);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.VRCXRuntime = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Feed) {
  'use strict';
  class StaleRequest extends Error { constructor() { super('Superseded request'); this.name = 'StaleRequest'; } }
  const ignored = e => e?.name === 'StaleRequest' || e?.name === 'AbortError';
  const clone = v => v == null ? v : JSON.parse(JSON.stringify(v));
  const ACCOUNT_NAMES = Object.freeze({a:'账号A', b:'账号B'});
  const LOGIN_ERROR = '登录异常';
  const loginLabel = (value, error) => !error && value?.logged_in === true && !value.error && value._auth_state !== 'error' ? '已登录' : LOGIN_ERROR;

  class AccountDirectory {
    constructor() { this.names = {...ACCOUNT_NAMES}; }
    setName(account, name) {
      if (!['a','b'].includes(account)) throw new Error('无效的账号');
      this.names[account] = typeof name === 'string' && name.trim() ? name.trim() : ACCOUNT_NAMES[account];
      return this.names[account];
    }
    observe(account, value) {
      return this.setName(account, loginLabel(value) === '已登录' ? value.name : null);
    }
  }

  class AccountUnavailable extends Error {
    constructor(account, reason, detail) {
      super(`${ACCOUNT_NAMES[account]}${LOGIN_ERROR}`);
      this.name = 'AccountUnavailable'; this.account = account; this.reason = reason;
      // Diagnostic detail stays out of the message rendered to the user.
      this.detail = detail || '';
    }
  }

  class Context {
    constructor(view = 'a') { this.view = ['a', 'b', 'm'].includes(view) ? view : 'a'; this.epoch = 0; this.pageEpoch = 0; }
    snapshot() { return {view: this.view, epoch: this.epoch, pageEpoch: this.pageEpoch}; }
    current(s, page = false) { return s.epoch === this.epoch && (!page || s.pageEpoch === this.pageEpoch); }
    select(view) {
      if (!['a', 'b', 'm'].includes(view)) throw new Error('无效的账号视角');
      if (this.view === view) return false;
      this.view = view; this.epoch++; this.pageEpoch++; return true;
    }
  }

  class Resources {
    constructor() { this.items = new Map(); }
    register(path, options = {}) { this.items.set(path, {scope: 'account', ttl: 2000, merge: false, ...options}); }
    get(path) {
      const key = path.split('?')[0], item = this.items.get(key);
      if (!item) throw new Error(`未注册的数据接口: ${key}`);
      return item;
    }
  }

  function resources() {
    const r = new Resources();
    const account = ['self', 'status', 'friends', 'feed', 'history', 'friendlog', 'mutual-graph',
      'favgroups', 'favorites', 'notifications', 'avatars', 'avatar', 'moderations', 'friend',
      'friend-section', 'world', 'instance', 'image', 'search', 'world-search', 'random-world', 'stats', 'group', 'group-search',
      'group-members', 'invite-messages', 'push-config', 'config', 'status-presets', 'backup',
      'export', 'export-events', 'set-status', 'friend-note', 'world-note', 'friend-delete',
      'log-delete', 'favgroup-create', 'favgroup-import', 'favorite-op', 'notification-act',
      'moderate', 'avatar-select', 'group-leave', 'preset-add', 'preset-remove', 'config-set',
      'push-config-set', 'backup-op', 'backup-restore', 'refresh', 'push-test', 'login', 'logout'];
    account.forEach(name => r.register('/api/' + name));
    ['self', 'status', 'friends', 'feed', 'history'].forEach(name => r.register('/api/' + name, {merge: true}));
    r.register('/api/self', {ttl: 10000, merge: true});
    // These settings are local to the account service, independent of VRChat login.
    ['config','push-config','backup'].forEach(name=>r.register('/api/'+name,{offline:true}));
    ['net-stats', 'ui-version', 'vrc-status', 'peer-self', 'peer-feed', 'peer-friends', 'peer-login', 'peer-logout'].forEach(name => r.register('/api/' + name, {scope: 'system', ttl: 5000}));
    return r;
  }

  class Client {
    constructor(context, transport, registry = resources(), clock = () => Date.now()) {
      this.context = context; this.transport = transport; this.registry = registry; this.clock = clock;
      this.cache = new Map(); this.pending = new Map(); this.revisions = new Map(); this.limit = 128;
      this.accountStates = new Map(); this.accountStatePending = new Map();
    }
    revision(account, path='') { return `${this.revisions.get(account)||0}:${this.revisions.get(account+'|'+path.split('?')[0])||0}`; }
    invalidate(account, paths) {
      // Fences requests which started before a mutation; old replies cannot refill cache.
      if (paths) paths.forEach(path=>{const key=account+'|'+path.split('?')[0];this.revisions.set(key,(this.revisions.get(key)||0)+1);});
      else this.revisions.set(account,(this.revisions.get(account)||0)+1);
      for (const key of this.cache.keys()) if (key.startsWith(account + '|') && (!paths || paths.some(p => key.slice(account.length + 1).startsWith(p)))) this.cache.delete(key);
    }
    peek(path, account = this.context.view) {
      this.registry.get(path);
      if (!['a','b','system'].includes(account)) return null;
      const hit = this.cache.get(account+'|'+path);
      return hit && hit.revision === this.revision(account,path) ? clone(hit.value) : null;
    }
    async source(path, account, options = {}) {
      const policy = this.registry.get(path), key = account + '|' + path, revision = this.revision(account, path);
      const hit = this.cache.get(key);
      if (!options.force && hit && hit.revision === revision && this.clock() - hit.at < policy.ttl) return clone(hit.value);
      let job = this.pending.get(key);
      if (!job || job.revision !== revision) {
        const url = account === 'b' ? '/api/peer-relay?path=' + encodeURIComponent(path) : path;
        job = {revision};
        job.promise = Promise.resolve().then(() => this.transport(url)).then(value => {
          if (revision !== this.revision(account, path)) throw new StaleRequest();
          if ((value?.error && !(path==='/api/self' && value.logged_in===false)) || value?.peer_error || value?.peer_configured===false) throw new Error(value.error || value.peer_error || '账号实例未配置');
          this.rememberAccountState(account, path, value);
          this.cache.delete(key);
          this.cache.set(key, {value: clone(value), at: this.clock(), revision});
          while (this.cache.size > this.limit) this.cache.delete(this.cache.keys().next().value);
          return value;
        }).catch(error=>{
          if(revision !== this.revision(account,path)) throw new StaleRequest();
          throw error;
        }).finally(() => { if (this.pending.get(key) === job) this.pending.delete(key); });
        this.pending.set(key, job);
      }
      return clone(await job.promise);
    }
    rememberAccountState(account, path, value) {
      if (!['a','b'].includes(account) || !['/api/status','/api/self'].includes(path) || typeof value?.logged_in !== 'boolean') return null;
      const status = value.logged_in ? 'logged_in' : 'not_logged_in';
      value._auth_state = status;
      const state = {
        state: status,
        checkedAt: this.clock(),
        value: clone(value),
        message: ''
      };
      this.accountStates.set(account, state);
      return state;
    }
    async accountStatus(account, options = {}) {
      const previous = this.accountStates.get(account);
      const fresh = previous && (previous.state !== 'logged_in' || this.clock() - previous.checkedAt < 30000);
      if (!options.force && fresh) return previous;
      const pending = this.accountStatePending.get(account);
      if (pending) return pending;
      const request = this.source('/api/status', account, {force: !!options.force}).then(value => {
        if (typeof value?.logged_in !== 'boolean') throw new Error('服务器没有返回登录状态');
        return this.accountStates.get(account) || this.rememberAccountState(account, '/api/status', value);
      }).catch(error => {
        if (ignored(error)) throw error;
        const state = {state:'error', checkedAt:this.clock(), value:null, message:error?.message || '无法读取登录状态'};
        this.accountStates.set(account, state);
        return state;
      }).finally(() => {
        if (this.accountStatePending.get(account) === request) this.accountStatePending.delete(account);
      });
      this.accountStatePending.set(account, request);
      return request;
    }
    async readAccount(path, account, options = {}, snapshot = this.context.snapshot()) {
      if(this.registry.get(path).offline)return this.source(path,account,options);
      if (account !== 'b' && !(account === 'a' && path === '/api/self')) return this.source(path, account, options);
      const state = await this.accountStatus(account, options);
      if (options.fenced !== false && !this.context.current(snapshot, true)) throw new StaleRequest();
      if (state.state === 'not_logged_in') {
        if (path === '/api/status') return {...(state.value || {}), logged_in:false, _auth_state:'not_logged_in'};
        if (path === '/api/self') return {logged_in:false, _auth_state:'not_logged_in'};
        throw new AccountUnavailable(account, state.state);
      }
      if (state.state === 'error') throw new AccountUnavailable(account, state.state, state.message);
      if (path === '/api/status') return clone(state.value);
      return this.source(path, account, options);
    }
    accountState(account) { return clone(this.accountStates.get(account) || null); }
    account(path,options,snapshot){
      const policy=this.registry.get(path);
      const account=policy.scope==='system'?'system':options.account||snapshot.view;
      if(!['a','b','m','system'].includes(account) || (policy.scope!=='system' && account==='system')) throw new Error('无效的数据来源');
      return account;
    }
    async read(path, options = {}) {
      const snapshot = this.context.snapshot(), policy = this.registry.get(path);
      const account = this.account(path,options,snapshot);
      try {
        let value;
        if (account === 'm') {
          if (!policy.merge) throw new Error('合并视角不支持此功能，请先选择一个账号');
          const result = await Promise.allSettled([this.readAccount(path, 'a', options, snapshot), this.readAccount(path, 'b', options, snapshot)]);
          value = Feed.mergePayload(...result.map(r => r.status === 'fulfilled' ? r.value : {error: r.reason.message}));
        } else value = await this.readAccount(path, account, options, snapshot);
        if (options.fenced !== false && !this.context.current(snapshot, true)) throw new StaleRequest();
        return value;
      } catch(error){
        if(options.fenced!==false && !this.context.current(snapshot,true)) throw new StaleRequest();
        throw error;
      }
    }
    async write(path, body, options = {}) {
      const snapshot=this.context.snapshot(), account=this.account(path,options,snapshot);
      if (account === 'm') return {ok: false, error: '合并视角只看不改，请先选择一个账号'};
      const url = account === 'b' ? '/api/peer-relay-post?path=' + encodeURIComponent(path) : path;
      try{
        const value = await this.transport(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        this.invalidate(account);
        if (value?.ok && ['/api/login','/api/logout','/api/peer-login','/api/peer-logout'].includes(path)) {
          const target = path.startsWith('/api/peer-') ? 'b' : account;
          this.invalidate(target); this.accountStatePending.delete(target);
          if (path.endsWith('logout')) this.accountStates.set(target, {state:'not_logged_in', checkedAt:this.clock(), value:{logged_in:false}, message:''});
          else this.accountStates.delete(target);
        }
        if(options.fenced!==false && !this.context.current(snapshot,true)) throw new StaleRequest();
        return value;
      }catch(error){
        if(options.fenced!==false && !this.context.current(snapshot,true)) throw new StaleRequest();
        throw error;
      }
    }
  }

  class Tasks {
    constructor(context) { this.context = context; this.slots = new Map(); }
    begin(key, page = true) {
      const id = (this.slots.get(key) || 0) + 1, snapshot = this.context.snapshot();
      this.slots.set(key, id);
      return {current: () => this.slots.get(key) === id && this.context.current(snapshot, page)};
    }
    cancel(key) { this.slots.set(key, (this.slots.get(key) || 0) + 1); }
  }

  class Pages {
    constructor(context, onError = () => {}) { this.context = context; this.items = new Map(); this.active = null; this.onError = onError; this.running = null; }
    register(id, spec) { this.items.set(id, {merged:false, interval:30000, ...spec}); }
    allows(id, view) { const spec = this.items.get(id); return !!spec && spec.available !== false && (view !== 'm' || spec.merged); }
    enter(id) {
      if (!this.allows(id, this.context.view)) id = 'feed';
      if (id !== this.active) {
        this.items.get(this.active)?.leave?.(); this.context.pageEpoch++; this.active = id;
      }
      // Refreshes from a previous route must never hold a new page's load hostage.
      if (this.running && !this.context.current(this.runningSnapshot, true)) this.running = null;
      this.refresh(true); return id;
    }
    refresh(entering = false) {
      const spec = this.items.get(this.active);
      if (!entering && (spec?.refresh===false || Date.now()-(spec?.last||0)<spec?.interval)) return this.running;
      if (!spec || this.running) return this.running;
      const snapshot = this.context.snapshot(), id = this.active;
      spec.last=Date.now();
      this.runningSnapshot = snapshot;
      const run = Promise.resolve().then(() => {
        if (this.active === id && this.context.current(snapshot, true)) return spec.load?.(entering);
      }).catch(e => {
        if (!ignored(e) && this.active === id && this.context.current(snapshot, true)) this.onError(e, id);
      }).finally(() => { if (this.running === run) this.running = null; });
      this.running = run; return run;
    }
  }

  class Scheduler {
    constructor() { this.jobs = new Map(); }
    add(id, ms, run) { this.jobs.set(id, {ms, run, last: -Infinity, busy: false}); }
    async tick(now = Date.now(), visible = true) {
      if (!visible) return;
      const jobs = [];
      for (const job of this.jobs.values()) {
        if (job.busy || now - job.last < job.ms) continue;
        job.last = now; job.busy = true;
        jobs.push(Promise.resolve().then(job.run).catch(e => { if (!ignored(e)) console.error(e); }).finally(() => { job.busy = false; }));
      }
      await Promise.all(jobs);
    }
    start() { this.stop(); this.timer = setInterval(() => this.tick(Date.now(), !document.hidden), 1000); }
    stop() { if (this.timer) clearInterval(this.timer); this.timer = null; }
  }
  class PageHistory {
    constructor(page='feed') { this.entries=[{page,key:0}];this.index=0;this.sequence=0; }
    get current() { return this.entries[this.index]; }
    get previous() { return this.entries[this.index-1] || null; }
    enter(page) {
      if(this.current.page===page) return this.current;
      this.entries.splice(this.index+1);
      this.entries.push({page,key:++this.sequence});
      if(this.entries.length>64) this.entries.shift();
      this.index=this.entries.length-1;
      return this.current;
    }
    restore(key,page) {
      const index=this.entries.findIndex(entry=>entry.key===key&&entry.page===page);
      if(index>=0) {this.index=index;return this.current;}
      // Browser history can outlive our bounded in-memory trail.
      this.entries=[{page,key:++this.sequence}];this.index=0;return this.current;
    }
    back() { if(this.previous) this.index--;return this.current; }
    prune(allowed) {
      const key=this.current.key,prior=this.entries.slice(0,this.index+1).filter(entry=>allowed(entry.page));
      this.entries=this.entries.filter(entry=>allowed(entry.page));
      this.index=this.entries.findIndex(entry=>entry.key===key);
      if(this.index<0)this.index=Math.max(0,prior.length-1);
      if(!this.entries.length){this.entries=[{page:'feed',key:++this.sequence}];this.index=0;}
    }
  }

  class RealtimeChannel {
    constructor({create,onState=()=>{},onFeed=()=>{},later=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id),timeout=8000,retry=30000}) {
      Object.assign(this,{create,onState,onFeed,later,cancel,timeout,retry});this.enabled=false;this.source=null;this.timer=null;
    }
    state(value) { this.onState(value); }
    clear() { if(this.timer!==null)this.cancel(this.timer);this.timer=null;this.source?.close();this.source=null; }
    start() {
      if(this.enabled) return;
      this.enabled=true;this.connect();
    }
    connect() {
      if(!this.enabled)return;
      this.clear();this.state('connecting');
      let source;
      const failed=()=>{
        if(!this.enabled||this.source!==source)return;
        this.clear();this.state('failed');
        this.timer=this.later(()=>{this.timer=null;this.connect();},this.retry);
      };
      try { source=this.create();this.source=source; }
      catch { this.state('failed');this.timer=this.later(()=>{this.timer=null;this.connect();},this.retry);return; }
      this.timer=this.later(failed,this.timeout);
      source.onopen=()=>{
        if(!this.enabled||this.source!==source)return;
        if(this.timer!==null)this.cancel(this.timer);this.timer=null;this.state('connected');
      };
      source.onerror=failed;
      source.addEventListener('feed',event=>{
        if(!this.enabled||this.source!==source)return;
        let value;try {value=JSON.parse(event.data);}catch{return;}
        this.onFeed(value);
      });
    }
    stop() { this.enabled=false;this.clear();this.state('idle'); }
  }

  function realtimeState(view, hasAccessToken, eventState) {
    const detail='这是网页与服务器的更新通道；VRChat 采集是否正常，请查看动态页的上次采集时间。';
    if (view === 'm') return {text:'页面更新：双号每 5 秒刷新',connected:false,detail};
    if (view === 'b' || hasAccessToken) return {text:'页面更新：每 5 秒刷新',connected:false,detail};
    if (eventState === 'connected') return {text:'页面更新：实时连接',connected:true,detail};
    if (eventState === 'connecting' || eventState === 'idle') return {text:'页面更新：连接中 · 定时刷新可用',connected:false,detail};
    return {text:'页面更新：每 5 秒刷新',connected:false,detail:detail+' 实时连接未建立，已使用定时刷新。'};
  }
  return {Context, Resources, resources, Client, Tasks, Pages, Scheduler, PageHistory, RealtimeChannel, StaleRequest, ignored, realtimeState, AccountDirectory, AccountUnavailable, ACCOUNT_NAMES, LOGIN_ERROR, loginLabel};
});
