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

// Analytics ids are read from the container environment at request time
// (force-dynamic: next start re-renders the layout per request, so a value
// added to the stack env takes effect on container start - no image rebuild).
// Empty = no analytics tags.
export const dynamic = "force-dynamic";

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
  const gaMeasurementId = process.env.GA_MEASUREMENT_ID || '';
  const clarityProjectId = process.env.CLARITY_PROJECT_ID || '';

  return (
    <html lang="en" className={`${pixelFont.variable} ${consoleFont.variable} ${bodyFont.variable}`}>
      <head>
        {gaMeasurementId !== '' && (
          <>
            <script
              async
              src={`https://www.googletagmanager.com/gtag/js?id=${gaMeasurementId}`}
            />
            <script
              dangerouslySetInnerHTML={{
                __html: `window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', '${gaMeasurementId}');`,
              }}
            />
          </>
        )}
        {clarityProjectId !== '' && (
          <script
            dangerouslySetInnerHTML={{
              __html: `(function(c,l,a,r,i,t,y){
c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
})(window, document, "clarity", "script", "${clarityProjectId}");`,
            }}
          />
        )}
      </head>
      <body className="bg-night text-ink font-body antialiased min-h-screen">
        <AuthProvider>
          <CozyBackdrop />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
