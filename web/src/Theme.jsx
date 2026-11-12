import React,{useEffect,useState} from 'react';
import {Dropdown,Option,webLightTheme,webDarkTheme} from '@fluentui/react-components';

export function useAppTheme(){
 const [choice,setChoice]=useState(()=>{try{return localStorage.getItem('dps-theme')||'system';}catch{return 'system';}});
 const [dark,setDark]=useState(()=>matchMedia('(prefers-color-scheme: dark)').matches);
 useEffect(()=>{const media=matchMedia('(prefers-color-scheme: dark)'),change=()=>setDark(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
 const resolved=choice==='system'?(dark?'dark':'light'):choice;
 useEffect(()=>{document.documentElement.dataset.theme=resolved;try{localStorage.setItem('dps-theme',choice);}catch{}},[choice,resolved]);
 const theme={...(resolved==='dark'?webDarkTheme:webLightTheme),fontFamilyBase:'"Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", sans-serif',borderRadiusMedium:'8px',
  colorBrandBackground:resolved==='dark'?'#86c6a6':'#216348',colorBrandBackgroundHover:resolved==='dark'?'#a0d7ba':'#194d38',colorBrandBackgroundPressed:'#16422f',
  colorBrandForeground1:resolved==='dark'?'#a0d7ba':'#216348',colorCompoundBrandBackground:resolved==='dark'?'#86c6a6':'#216348',
  colorCompoundBrandBackgroundHover:resolved==='dark'?'#a0d7ba':'#194d38',colorCompoundBrandForeground1:resolved==='dark'?'#a0d7ba':'#216348',
  colorNeutralForegroundOnBrand:resolved==='dark'?'#12251b':'#f7faf8'};
 return {theme,choice,setChoice};
}
export function ThemePicker({value,onChange}){
 const choices=[['system','跟随系统'],['light','浅色界面'],['dark','深色界面']];
 return <Dropdown className="theme-picker" aria-label="界面主题" value={choices.find(x=>x[0]===value)?.[1]} selectedOptions={[value]} onOptionSelect={(_,d)=>onChange(d.optionValue)}>{choices.map(([key,label])=><Option key={key} value={key}>{label}</Option>)}</Dropdown>;
}
