require 'jekyll'

Liquid::Template.register_filter(Jekyll::Filters)
root = File.expand_path('..', __dir__)
assignments = File.read(File.join(root, 'linkedin.html')).partition('<!DOCTYPE html>').first
template = Liquid::Template.parse(assignments + "POST_IDS:{{ posts | map: 'id' | join: ',' }}")
fixtures = [
  ['unknown', nil], ['zero', 0], ['below', 49], ['boundary', 50],
  ['eligible', 51], ['highest', 100]
].map { |id, reactions| { 'id' => id, 'reactions' => reactions } }

[[fixtures, 'highest,eligible'], [fixtures.reverse, 'highest,eligible'],
 [fixtures.first(4), ''], [[], '']].each do |posts, expected|
  context = { 'site' => { 'data' => { 'linkedin' => { 'posts' => posts } } } }
  actual = template.render!(context, strict_filters: true).partition('POST_IDS:').last.strip
  abort "LinkedIn cutoff: expected #{expected.inspect}, got #{actual.inspect}" unless actual == expected
end

puts 'OK: LinkedIn excludes missing counts and counts <= 50, sorted by reactions.'
