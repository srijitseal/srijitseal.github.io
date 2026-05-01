
$(document).ready(function() {
    $('.publication-mousecell').mouseover(function() {
        $(this).find('video').css('display', 'inline-block');
        $(this).find('img').css('display', 'none');
    });
    $('.publication-mousecell').mouseout(function() {
        $(this).find('video').css('display', 'none');
        $(this).find('img').css('display', 'inline-block');
    });

    function setActiveButton(buttons, activeButton) {
        buttons.forEach(function(button) {
            var isActive = button === activeButton;
            button.classList.toggle('is-active', isActive);
            button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
    }

    function setupPublicationFilters() {
        var buttons = Array.from(document.querySelectorAll('[data-publication-filter]'));
        var publications = Array.from(document.querySelectorAll('[data-publication]'));
        var emptyMessage = document.querySelector('[data-publication-empty]');
        var earlierPublications = document.querySelector('.earlier-publications');
        if (!buttons.length || !publications.length) {
            return;
        }

        function applyFilter(filter) {
            var visibleCount = 0;
            var visibleEarlierCount = 0;

            publications.forEach(function(publication) {
                var tags = (publication.dataset.tags || '').split(/\s+/).filter(Boolean);
                var isVisible = filter === 'all' || tags.indexOf(filter) !== -1;
                publication.hidden = !isVisible;
                if (isVisible) {
                    visibleCount += 1;
                    if (earlierPublications && earlierPublications.contains(publication)) {
                        visibleEarlierCount += 1;
                    }
                }
            });

            if (earlierPublications) {
                if (filter === 'all') {
                    earlierPublications.hidden = false;
                    earlierPublications.open = false;
                } else {
                    earlierPublications.hidden = visibleEarlierCount === 0;
                    earlierPublications.open = visibleEarlierCount > 0;
                }
            }

            if (emptyMessage) {
                emptyMessage.hidden = visibleCount > 0;
            }
        }

        buttons.forEach(function(button) {
            button.addEventListener('click', function() {
                setActiveButton(buttons, button);
                applyFilter(button.dataset.publicationFilter || 'all');
            });
        });
    }

    function parseTalkDate(dateText) {
        var months = {
            january: 0,
            february: 1,
            march: 2,
            april: 3,
            may: 4,
            june: 5,
            july: 6,
            august: 7,
            september: 8,
            october: 9,
            november: 10,
            december: 11
        };
        var parts = (dateText || '').trim().split(/\s+/);
        if (parts.length < 2) {
            return null;
        }
        var month = months[parts[0].toLowerCase()];
        var year = parseInt(parts[parts.length - 1], 10);
        if (month === undefined || Number.isNaN(year)) {
            return null;
        }
        return new Date(year, month + 1, 0, 23, 59, 59);
    }

    function setupTalkFilters() {
        var buttons = Array.from(document.querySelectorAll('[data-talk-filter]'));
        var talks = Array.from(document.querySelectorAll('[data-talk]'));
        var emptyMessage = document.querySelector('[data-talk-empty]');
        if (!buttons.length || !talks.length) {
            return;
        }

        talks.forEach(function(talk) {
            if (!talk.dataset.explicitStatus) {
                var talkEndDate = parseTalkDate(talk.dataset.date);
                if (talkEndDate && talkEndDate < new Date()) {
                    talk.dataset.status = 'completed';
                    talk.classList.add('is-completed');
                }
            }
        });

        function applyFilter(filter) {
            var visibleCount = 0;
            talks.forEach(function(talk) {
                var isVisible = filter === 'all' ||
                    talk.dataset.status === filter ||
                    talk.dataset.year === filter ||
                    talk.dataset.kind === filter;
                talk.hidden = !isVisible;
                if (isVisible) {
                    visibleCount += 1;
                }
            });

            if (emptyMessage) {
                emptyMessage.hidden = visibleCount > 0;
            }
        }

        buttons.forEach(function(button) {
            button.addEventListener('click', function() {
                setActiveButton(buttons, button);
                applyFilter(button.dataset.talkFilter || 'all');
            });
        });
    }

    setupPublicationFilters();
    setupTalkFilters();
})
