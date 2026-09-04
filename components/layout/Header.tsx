'use client';
import {Bell,Settings,User} from 'lucide-react';
export default function Header(){
return(
<header className="sticky top-0 z-50 border-b bg-white/80 backdrop-blur">
<div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
<div><h1 className="text-xl font-bold text-green-700">Think Along</h1><p className="text-xs text-gray-500">Think Better, Every Day</p></div>
<div className="flex gap-3"><Bell size={20}/><Settings size={20}/><User size={20}/></div>
</div>
</header>);
}
