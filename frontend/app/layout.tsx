import './globals.css';
import { AuthProvider } from '../context/AuthContext';
import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Eepy Host',
  description: 'Cyber-Cozy Hosting for MCP Servers',
  icons: {
    icon: '/favicon.png',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-void text-white antialiased">
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
