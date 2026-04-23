# srijitseal.github.io

Personal website for https://srijitseal.com, hosted with GitHub Pages from this repository.

The original template comes from https://github.com/keunhong/keunhong.github.io.

## Local Development

This site is built with Jekyll/GitHub Pages. Opening `index.html` directly in a browser will not fully render Liquid templates or data files, so use the Jekyll server for an accurate preview.

```bash
bundle install
bundle exec jekyll serve
```

Then open http://127.0.0.1:4000.

The project expects Ruby 3.3.4, matching `.ruby-version`. `Gemfile.lock` is intentionally ignored so GitHub Pages can resolve the supported gem set during deployment.

## Deployment

Pushing changes to the `main` branch publishes the site through GitHub Pages. The custom domain is configured in `CNAME`.

# License
<a rel="license" href="http://creativecommons.org/licenses/by-sa/4.0/"><img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by-sa/4.0/88x31.png" /></a><br />This work is licensed under a <a rel="license" href="http://creativecommons.org/licenses/by-sa/4.0/">Creative Commons Attribution-ShareAlike 4.0 International License</a>.
