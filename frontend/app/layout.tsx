import './globals.css';
import { AuthProvider } from '../context/AuthContext';
import CozyBackdrop from '../src/components/CozyBackdrop';
import { Metadata } from 'next';
import { Pixelify_Sans, VT323, Nunito } from 'next/font/google';

const pixelFont = Pixelify_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-pixel',
  display: 'swap',
});

const consoleFont = VT323({
  subsets: ['latin'],
  weight: '400',
  variable: '--font-console',
  display: 'swap',
});

const bodyFont = Nunito({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
  variable: '--font-body',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Eepy Host',
  description: 'Cozy retro hosting for MCP servers',
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
    <html lang="en" className={`${pixelFont.variable} ${consoleFont.variable} ${bodyFont.variable}`}>
      <body className="bg-night text-ink font-body antialiased min-h-screen">
        <AuthProvider>
          <CozyBackdrop />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
