import Sidebar from './Sidebar';
import Header from './Header';

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-base-900">
      <Sidebar />
      <Header />
      <main className="ml-56 mt-12 p-6 animate-fade-in">{children}</main>
    </div>
  );
}