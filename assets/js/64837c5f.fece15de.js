"use strict";(self.webpackChunkwebsite=self.webpackChunkwebsite||[]).push([[943],{3905:function(e,t,n){n.d(t,{Zo:function(){return c},kt:function(){return f}});var r=n(7294);function a(e,t,n){return t in e?Object.defineProperty(e,t,{value:n,enumerable:!0,configurable:!0,writable:!0}):e[t]=n,e}function o(e,t){var n=Object.keys(e);if(Object.getOwnPropertySymbols){var r=Object.getOwnPropertySymbols(e);t&&(r=r.filter((function(t){return Object.getOwnPropertyDescriptor(e,t).enumerable}))),n.push.apply(n,r)}return n}function l(e){for(var t=1;t<arguments.length;t++){var n=null!=arguments[t]?arguments[t]:{};t%2?o(Object(n),!0).forEach((function(t){a(e,t,n[t])})):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(n)):o(Object(n)).forEach((function(t){Object.defineProperty(e,t,Object.getOwnPropertyDescriptor(n,t))}))}return e}function i(e,t){if(null==e)return{};var n,r,a=function(e,t){if(null==e)return{};var n,r,a={},o=Object.keys(e);for(r=0;r<o.length;r++)n=o[r],t.indexOf(n)>=0||(a[n]=e[n]);return a}(e,t);if(Object.getOwnPropertySymbols){var o=Object.getOwnPropertySymbols(e);for(r=0;r<o.length;r++)n=o[r],t.indexOf(n)>=0||Object.prototype.propertyIsEnumerable.call(e,n)&&(a[n]=e[n])}return a}var s=r.createContext({}),u=function(e){var t=r.useContext(s),n=t;return e&&(n="function"==typeof e?e(t):l(l({},t),e)),n},c=function(e){var t=u(e.components);return r.createElement(s.Provider,{value:t},e.children)},p={inlineCode:"code",wrapper:function(e){var t=e.children;return r.createElement(r.Fragment,{},t)}},d=r.forwardRef((function(e,t){var n=e.components,a=e.mdxType,o=e.originalType,s=e.parentName,c=i(e,["components","mdxType","originalType","parentName"]),d=u(n),f=a,k=d["".concat(s,".").concat(f)]||d[f]||p[f]||o;return n?r.createElement(k,l(l({ref:t},c),{},{components:n})):r.createElement(k,l({ref:t},c))}));function f(e,t){var n=arguments,a=t&&t.mdxType;if("string"==typeof e||a){var o=n.length,l=new Array(o);l[0]=d;var i={};for(var s in t)hasOwnProperty.call(t,s)&&(i[s]=t[s]);i.originalType=e,i.mdxType="string"==typeof e?e:a,l[1]=i;for(var u=2;u<o;u++)l[u]=n[u];return r.createElement.apply(null,l)}return r.createElement.apply(null,n)}d.displayName="MDXCreateElement"},1945:function(e,t,n){n.r(t),n.d(t,{frontMatter:function(){return i},contentTitle:function(){return s},metadata:function(){return u},toc:function(){return c},default:function(){return d}});var r=n(7462),a=n(3366),o=(n(7294),n(3905)),l=["components"],i={sidebar_label:"fakts",title:"fakts"},s=void 0,u={unversionedId:"reference/fakts",id:"reference/fakts",title:"fakts",description:"Fakts Objects",source:"@site/docs/reference/fakts.md",sourceDirName:"reference",slug:"/reference/fakts",permalink:"/fakts/docs/reference/fakts",editUrl:"https://github.com/jhnnsrs/fakts/edit/master/website/docs/reference/fakts.md",tags:[],version:"current",frontMatter:{sidebar_label:"fakts",title:"fakts"},sidebar:"tutorialSidebar",previous:{title:"errors",permalink:"/fakts/docs/reference/errors"},next:{title:"utils",permalink:"/fakts/docs/reference/utils"}},c=[{value:"Fakts Objects",id:"fakts-objects",children:[{value:"load_on_enter",id:"load_on_enter",children:[],level:4},{value:"delete_on_exit",id:"delete_on_exit",children:[],level:4},{value:"aget",id:"aget",children:[],level:4}],level:2}],p={toc:c};function d(e){var t=e.components,n=(0,a.Z)(e,l);return(0,o.kt)("wrapper",(0,r.Z)({},p,n,{components:t,mdxType:"MDXLayout"}),(0,o.kt)("h2",{id:"fakts-objects"},"Fakts Objects"),(0,o.kt)("pre",null,(0,o.kt)("code",{parentName:"pre",className:"language-python"},"class Fakts(KoiledModel)\n")),(0,o.kt)("h4",{id:"load_on_enter"},"load","_","on","_","enter"),(0,o.kt)("p",null,"Should we load on connect?"),(0,o.kt)("h4",{id:"delete_on_exit"},"delete","_","on","_","exit"),(0,o.kt)("p",null,"Should we delete on connect?"),(0,o.kt)("h4",{id:"aget"},"aget"),(0,o.kt)("pre",null,(0,o.kt)("code",{parentName:"pre",className:"language-python"},"async def aget(group_name: str, bypass_middleware=False, auto_load=False, validate: BaseModel = None)\n")),(0,o.kt)("p",null,"Get Config"),(0,o.kt)("p",null,"Gets the currently active configuration for the group_name. This is a loop\nsave function, and will guard the current fakts state through an async lock."),(0,o.kt)("p",null,"Steps:"),(0,o.kt)("ol",null,(0,o.kt)("li",{parentName:"ol"},"Acquire lock."),(0,o.kt)("li",{parentName:"ol"},"If not yet loaded and auto_load is True, load (reloading should be done seperatily)"),(0,o.kt)("li",{parentName:"ol"},"Pass through middleware (can be opt out by setting bypass_iddleware to True)"),(0,o.kt)("li",{parentName:"ol"},"Return groups fakts")),(0,o.kt)("p",null,(0,o.kt)("strong",{parentName:"p"},"Arguments"),":"),(0,o.kt)("ul",null,(0,o.kt)("li",{parentName:"ul"},(0,o.kt)("inlineCode",{parentName:"li"},"group_name")," ",(0,o.kt)("em",{parentName:"li"},"str")," - The group name in the fakts"),(0,o.kt)("li",{parentName:"ul"},(0,o.kt)("inlineCode",{parentName:"li"},"bypass_middleware")," ",(0,o.kt)("em",{parentName:"li"},"bool, optional")," - Bypasses the Middleware (e.g. no overwrites). Defaults to False."),(0,o.kt)("li",{parentName:"ul"},(0,o.kt)("inlineCode",{parentName:"li"},"auto_load")," ",(0,o.kt)("em",{parentName:"li"},"bool, optional")," - Should we autoload the configuration through grants if nothing has been set? Defaults to True.")),(0,o.kt)("p",null,(0,o.kt)("strong",{parentName:"p"},"Returns"),":"),(0,o.kt)("ul",null,(0,o.kt)("li",{parentName:"ul"},(0,o.kt)("inlineCode",{parentName:"li"},"dict")," - The active fakts")))}d.isMDXComponent=!0}}]);