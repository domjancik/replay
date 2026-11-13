import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
class Element {
  constructor(){this.children=[];this.value='';this.dataset={};this.attrs={};this.scrollTop=0;this.classList={toggle(){}};}
  setAttribute(k,v){this.attrs[k]=v;}
  append(...children){for(const child of children){child.detach();child.parentElement=this;this.children.push(child);}}
  detach(){if(this.parentElement){const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this),1);this.parentElement=null;}}
  after(child){child.detach();const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this)+1,0,child);child.parentElement=this.parentElement;}
  replaceChildren(){for(const child of this.children)child.parentElement=null;this.children=[];this.scrollTop=0;}
  querySelectorAll(){return [];}
}
function fixture(){
 const elements=new Map();const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const root=new Element();root.append(el('notebook-gallery'),el('page-drawer'));el('page-drawer').append(el('page-gallery'));
 const context=vm.createContext({document:{getElementById:el,createElement:()=>new Element()},window:{addEventListener(){}},getComputedStyle:()=>({gridTemplateColumns:'1fr 1fr 1fr 1fr'}),setTimeout,clearTimeout});
 vm.runInContext(readFileSync(new URL('../../src/rm_redraw/web/static/app.js',import.meta.url),'utf8').replace('safely(start)();',''),context);
 vm.runInContext(`library=Array.from({length:6},(_,i)=>({id:String(i),name:'Notebook '+i,pages:Array.from({length:21},(_,p)=>({id:String(p),number:p+1,available:true}))}));expandedNotebook='1';$('notebook').value='1';renderGallery();setupGallery();`,context);
 return {el,context};
}
test('drawer is inline after selected row and opens into pages-only view',()=>{
 const {el}=fixture();assert.equal(el('notebook-gallery').children[4],el('page-drawer'));assert.equal(el('page-gallery').children.length,21);
 el('drawer-open').onclick();assert.equal(el('notebook-gallery').hidden,true);assert.equal(el('page-drawer').hidden,false);assert.equal(el('drawer-open').hidden,true);
 el('drawer-close').onclick();assert.equal(el('notebook-gallery').hidden,false);assert.equal(el('notebook-gallery').children[4],el('page-drawer'));
 el('drawer-close').onclick();assert.equal(el('page-drawer').hidden,true);
});
test('selecting pages preserves internal scroll, switching notebook resets it',()=>{
 const {el,context}=fixture();el('page-gallery').scrollTop=210;vm.runInContext("$('page').value='18';renderGallery();",context);
 assert.equal(el('page-gallery').scrollTop,210);
 assert.equal(el('page-gallery').children[18].attrs['aria-pressed'],'true');
 vm.runInContext("expandedNotebook='2';renderGallery();",context);assert.equal(el('page-gallery').scrollTop,0);
});
