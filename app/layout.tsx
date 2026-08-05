import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import './globals.css';

export const metadata: Metadata = {
  title: 'DebtoIPA — Stock iOS Packager',
  description: 'Analyze iOS Debian packages and package compatible app bundles as sideloadable IPA files.',
  applicationName: 'DebtoIPA',
  manifest: '/manifest.webmanifest',
  icons: { icon: '/icon.svg', apple: '/icon.svg' },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#070914',
};

const iosFilePickerFix = `
(() => {
  const patchInput = (input) => {
    if (!(input instanceof HTMLInputElement) || input.type !== 'file') return;

    input.removeAttribute('accept');
    input.hidden = false;
    input.setAttribute('aria-label', 'Choose a Debian package');
    Object.assign(input.style, {
      position: 'absolute',
      inset: '0',
      width: '100%',
      height: '100%',
      opacity: '0',
      zIndex: '3',
      cursor: 'pointer',
    });

    const zone = input.closest('.upload-zone');
    if (zone instanceof HTMLElement) zone.style.position = 'relative';

    if (input.dataset.iosPickerPatched !== 'yes') {
      input.dataset.iosPickerPatched = 'yes';
      input.addEventListener('click', (event) => event.stopPropagation());
    }
  };

  const patchAll = () => {
    document.querySelectorAll('input[type="file"]').forEach(patchInput);
  };

  window.addEventListener('load', () => {
    patchAll();
    new MutationObserver(patchAll).observe(document.body, { childList: true, subtree: true });
    document.addEventListener('pointerdown', (event) => {
      const target = event.target;
      const zone = target instanceof Element ? target.closest('.upload-zone') : null;
      const input = zone?.querySelector('input[type="file"]');
      if (input) patchInput(input);
    }, true);
  }, { once: true });
})();
`;

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        {children}
        <script dangerouslySetInnerHTML={{ __html: iosFilePickerFix }} />
      </body>
    </html>
  );
}
