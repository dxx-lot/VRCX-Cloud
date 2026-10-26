/* Instance-local raster loading. Every asynchronous result belongs to its node
 * and captured account; rebuilding a detail cannot revive an old image. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports) module.exports=api;
  else root.VRCXImages=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const inline=url=>/^data:image\//.test(url);
  const path=url=>'/api/image?url='+encodeURIComponent(url);
  const valid=src=>/^\/media\/(?:peer\/)?[a-f0-9]{64}\/[a-f0-9]{64}$/.test(src||'');
  class Manager{
    constructor({read,peek=()=>null,fallback=()=>{},limit=4,now=()=>Date.now()}){
      Object.assign(this,{read,peek,fallback,limit,now});this.states=new WeakMap();this.jobs=new Map();this.queue=[];this.busy=0;
    }
    attrs(url,account,priority='auto'){
      if(!url) return '';
      const cached=this.peek(path(url),account),src=inline(url)?url:valid(cached?.src)?cached.src:'';
      return `loading="${priority==='high'?'eager':'lazy'}"${priority==='high'?' fetchpriority="high" data-media-priority="high"':''} onerror="IMAGES.failed(this)" data-media-url="${escape(url)}" data-media-account="${escape(account)}"${src?` src="${escape(src)}"`:''}`;
    }
    ticket(url,account,force=false,priority=false){
      const key=account+'|'+url+'|'+force;
      if(this.jobs.has(key)){
        const index=this.queue.findIndex(job=>job.key===key);
        if(priority&&index>0)this.queue.unshift(this.queue.splice(index,1)[0]);
        return this.jobs.get(key);
      }
      if(this.queue.length>=256) return Promise.reject(new Error('图片加载繁忙'));
      const job=new Promise((resolve,reject)=>{this.queue[priority?'unshift':'push']({key,url,account,force,resolve,reject});this.pump();})
        .finally(()=>this.jobs.delete(key));
      this.jobs.set(key,job);return job;
    }
    pump(){
      while(this.busy<this.limit&&this.queue.length){
        const job=this.queue.shift();this.busy++;
        Promise.resolve().then(()=>this.read(path(job.url),{account:job.account,fenced:false,force:job.force}))
          .then(value=>{if(!valid(value?.src)) throw new Error('图片暂不可用');job.resolve(value.src);},job.reject)
          .catch(job.reject).finally(()=>{this.busy--;this.pump();});
      }
    }
    clear(image){
      this.states.delete(image);delete image.dataset.mediaUrl;delete image.dataset.mediaAccount;
      image.onerror=null;image.removeAttribute('src');image.style.visibility='hidden';
    }
    setURL(image,url,account,priority='auto'){
      if(!url){this.clear(image);return;}
      if(image.dataset.mediaAccount!==account||image.dataset.mediaUrl!==url)this.clear(image);
      image.dataset.mediaPriority=priority;
      image.dataset.mediaUrl=url;image.dataset.mediaAccount=account;this.hydrate(image);
    }
    capture(container,pending=false){
      return [...container.querySelectorAll('img[data-media-url]')].filter(image=>pending||(image.complete&&image.naturalWidth>0));
    }
    restore(container,photos){
      for(const replacement of container.querySelectorAll('img[data-media-url]')){
        let chain=[];try{chain=JSON.parse(replacement.dataset.photos||'[]');}catch{}
        const index=photos.findIndex(image=>image.dataset.mediaAccount===replacement.dataset.mediaAccount&&
          image.className===replacement.className&&(image.dataset.mediaUrl===replacement.dataset.mediaUrl||chain.includes(image.dataset.mediaUrl)));
        if(index<0) continue;
        const image=photos.splice(index,1)[0];
        if(replacement.dataset.photos){
          image.dataset.photos=replacement.dataset.photos;
          image.dataset.photoIndex=String(Math.max(0,chain.indexOf(image.dataset.mediaUrl)));
        }
        image.alt=replacement.alt;replacement.replaceWith(image);
      }
    }
    hydrate(image,force=false){
      if(image.isConnected===false) return;
      const {mediaUrl:url,mediaAccount:account}=image.dataset;
      if(!url||!['a','b'].includes(account)) return;
      const old=this.states.get(image);
      if(!force&&old?.url===url&&old.account===account){
        if(!old.failed||this.now()<old.retryAt)return;
        force=true;
      }
      const attempts=old?.url===url&&old.account===account?(old.attempts||0)+1:0;
      const state={url,account,retried:force,attempts};this.states.set(image,state);
      image.onerror=()=>this.failed(image);
      const current=()=>image.isConnected!==false&&this.states.get(image)===state&&image.dataset.mediaUrl===url&&image.dataset.mediaAccount===account;
      if(inline(url)){image.style.visibility='';image.src=url;return;}
      this.ticket(url,account,force,image.dataset.mediaPriority==='high').then(src=>{
        if(current()){
          image.hidden=false;image.style.display='';image.style.visibility='';
          image.removeAttribute('title');image.removeAttribute('aria-label');
          if(image.getAttribute('src')!==src)image.src=src;
        }
      }).catch(()=>{if(current())this.unavailable(image);});
    }
    unavailable(image){
      const state=this.states.get(image);
      if(state){state.failed=true;state.retryAt=this.now()+Math.min(60000,5000*2**Math.min(state.attempts,4));}
      // A temporary fetch failure never erases a picture already decoded.
      if(image.complete&&image.naturalWidth>0) return;
      if(image.dataset.photos) this.fallback(image);
      else {image.removeAttribute('src');image.style.visibility='hidden';image.title='图片暂不可用';image.setAttribute('aria-label','图片暂不可用');}
    }
    failed(image){
      if(image.isConnected===false) return;
      const state=this.states.get(image);
      if(!state){this.hydrate(image);return;}
      if(!state.retried&&!inline(state.url)) this.hydrate(image,true);
      else this.unavailable(image);
    }
    scan(node){
      const visit=image=>this.visibility&&image.dataset.mediaPriority!=='high'?this.visibility.observe(image):this.hydrate(image);
      if(node.matches?.('img[data-media-url]')) visit(node);
      node.querySelectorAll?.('img[data-media-url]').forEach(visit);
    }
    start(document){
      if(typeof IntersectionObserver!=='undefined')this.visibility=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){this.visibility.unobserve(entry.target);this.hydrate(entry.target);}}),{rootMargin:'180px'});
      this.scan(document);
      this.observer=new MutationObserver(records=>records.forEach(record=>{
        if(record.type==='attributes')this.hydrate(record.target);
        else record.addedNodes.forEach(node=>this.scan(node));
      }));
      this.observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['data-media-url','data-media-account','data-media-priority']});
    }
  }
  return {Manager};
});
if(typeof module==='undefined'||!module.exports){
  var IMAGES=new VRCXImages.Manager({read:(path,options)=>gGet(path,options),peek:(path,account)=>APP.client.peek(path,account),fallback:image=>detailPhotoError(image)});
  function mediaAttrs(url,account=GA,priority='auto'){return IMAGES.attrs(url,account==='b'?'b':'a',priority);}
}
