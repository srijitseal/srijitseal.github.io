require 'yaml'
require 'date'

root = File.expand_path('..', __dir__)
publications = YAML.load_file(File.join(root, '_data/publications.yml'))
authors = YAML.load_file(File.join(root, '_data/authors.yml'))
talks = YAML.load_file(File.join(root, '_data/upcoming_talks.yml'))
errors = []
ids = publications.map { |paper| paper.fetch('id') }
errors << 'Duplicate publication IDs' unless ids.uniq == ids
publications.each do |paper|
  paper.fetch('authors').each do |author|
    errors << "#{paper['id']}: missing author #{author}" unless authors.key?(author)
  end
  next unless paper['image']
  image = File.join(root, 'images', paper['image'])
  errors << "#{paper['id']}: missing or empty image #{paper['image']}" unless File.file?(image) && File.size(image).positive?
end
talks.each do |talk|
  errors << "#{talk['id']}: display date must be month and year" unless talk.fetch('date').match?(/\A[A-Z][a-z]+ 20\d{2}\z/)
  %w[session_date end_date].each do |key|
    next unless talk[key]
    begin
      Date.iso8601(talk[key])
    rescue ArgumentError
      errors << "#{talk['id']}: invalid #{key}"
    end
  end
end
%w[404.html redirect.html].each do |file|
  content = File.read(File.join(root, file))
  errors << "#{file}: current calendar destination changed" unless content.include?('https://calendly.com/srijitseal-vy1g/30-mins-srijit')
end
abort errors.join("\n") unless errors.empty?
puts "OK: #{publications.length} publications, #{publications.count { |p| p['image'] }} thumbnails, #{talks.length} talks, and current calendar redirects."
