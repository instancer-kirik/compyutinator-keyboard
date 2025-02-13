# Maintainer: instancer-kirik <106033356+instancer-kirik@users.noreply.github.com>

pkgname=compyutinator-tools
pkgver=0.6.7
pkgrel=1
pkgdesc="Compyutinator system tools - Keyboard Manager and Speech Transcriber"
arch=('any')
url="https://github.com/instancer-kirik/compyutinator-tools"
license=('GPL-3')
depends=(
    'python'
    'python-pyqt6'
    'kmonad'
    'python-vosk'
    'python-pyaudio'
    'python-numpy'
    'python-pyautogui'
    'python-requests'
    'python-tqdm'
    'tk'
)
makedepends=(
    'python-poetry'
    'python-build'
    'python-installer'
)

package() {
    cd "$srcdir/$pkgname-$pkgver"
    
    # Install Python package
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Install executables
    install -Dm755 "bin/compyutinator-keyboard" "$pkgdir/usr/bin/compyutinator-keyboard"
    install -Dm755 "bin/compyutinator-transcriber" "$pkgdir/usr/bin/compyutinator-transcriber"
    
    # Install desktop files
    install -Dm644 "share/applications/compyutinator-keyboard.desktop" \
        "$pkgdir/usr/share/applications/compyutinator-keyboard.desktop"
    install -Dm644 "share/applications/compyutinator-transcriber.desktop" \
        "$pkgdir/usr/share/applications/compyutinator-transcriber.desktop"
} 