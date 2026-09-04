import Header from './Header';
import BottomNavigation from './BottomNavigation';
export default function AppLayout({children}:{children:React.ReactNode}){
return <><Header/><main className="mx-auto max-w-6xl px-6 py-6 pb-24">{children}</main><BottomNavigation/></>;
}
