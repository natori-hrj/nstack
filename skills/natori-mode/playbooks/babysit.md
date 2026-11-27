# babysit

Track the exact current PR head SHA and inspect CI, conflicts and review evidence. Distinguish an unavailable service from a failing check. Retry transient failures within the agreed budget, or once in total if no budget is specified. Revalidate affected checks after the head changes. Apply the global review budget and delivery rules. Stop when the PR is ready to merge or a concrete blocker remains.
