module.exports = {
  content: [
    "./*.html",         // Ana klasördeki tüm .html dosyalarını tarar
    "./**/*.html",      // Alt klasörlerdeki .html dosyalarını da tarar
    "./*.{js,jsx,ts,tsx}", // JavaScript dosyaları varsa tarar (opsiyonel)
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}