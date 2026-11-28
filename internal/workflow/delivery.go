package workflow

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
)

type delivery struct {
	repo                    gitRepo
	options                 options
	base                    string
	remote, github          string
	config                  []string
	defaultRef, remoteStart string
	prBaseRef               string
	number                  int
}

func newDelivery(ctx context.Context, repo gitRepo, o options, base, start string, writerRequired bool) (*delivery, error) {
	if err := repo.branchRef(ctx, o.deliveryRef); err != nil {
		return nil, err
	}
	var id [16]byte
	if _, err := rand.Read(id[:]); err != nil {
		return nil, err
	}
	d := &delivery{repo: repo, options: o, base: base, remote: "nstack-delivery-" + hex.EncodeToString(id[:]), number: o.prNumber}
	if o.prBase != "" {
		d.prBaseRef = "refs/heads/" + o.prBase
		if err := repo.branchRef(ctx, d.prBaseRef); err != nil {
			return nil, err
		}
	}
	var err error
	if d.config, d.github, err = d.target(ctx); err != nil {
		return nil, err
	}
	if d.defaultRef, err = d.remoteDefault(ctx); err != nil {
		return nil, err
	}
	if d.remoteStart, err = d.remoteRef(ctx, o.deliveryRef); err != nil {
		return nil, err
	}
	if writerRequired && d.remoteStart != "" && d.remoteStart != start {
		return nil, errors.New("delivery ref does not match the starting candidate")
	}
	if d.github != "" && d.number == 0 {
		if d.number, err = d.openPR(ctx); err != nil {
			return nil, err
		}
	}
	return d, d.check(ctx, start)
}

var githubTarget = regexp.MustCompile(`(?i)^(?:https://github[.]com/|git@github[.]com:|ssh://git@github[.]com/)([a-z0-9-]+/[a-z0-9_.-]+)$`)

func (d *delivery) target(ctx context.Context) ([]string, string, error) {
	known, err := d.repo.git(ctx, "remote")
	if err != nil {
		return nil, "", err
	}
	var config []string
	source := d.options.push
	if !slices.Contains(strings.Split(known, "\n"), source) {
		source = d.remote
		config = []string{"-c", "remote." + d.remote + ".url=" + d.options.push}
	}
	urls, err := d.remoteURLs(ctx, source, "push", config)
	if err != nil {
		return nil, "", err
	}
	if len(urls) != 1 || urls[0] == "" {
		return nil, "", errors.New("delivery requires exactly one push destination")
	}
	target := urls[0]
	github := ""
	if d.options.githubRepo != "" {
		match := githubTarget.FindStringSubmatch(target)
		if match == nil || !strings.EqualFold(strings.TrimSuffix(match[1], ".git"), d.options.githubRepo) {
			return nil, "", errors.New("GitHub PR repository must match the Git push destination")
		}
		github = "github.com/" + strings.TrimSuffix(match[1], ".git")
	}
	// Verify that the pinned destination does not undergo a second Git rewrite.
	config = []string{"-c", "remote." + d.remote + ".url=" + target, "-c", "remote." + d.remote + ".pushurl=" + target}
	for _, direction := range []string{"fetch", "push"} {
		urls, err := d.remoteURLs(ctx, d.remote, direction, config)
		if err != nil {
			return nil, "", err
		}
		if !slices.Equal(urls, []string{target}) {
			return nil, "", errors.New("Git would rewrite the pinned delivery destination")
		}
	}
	return config, github, nil
}

func (d *delivery) remoteURLs(ctx context.Context, name, direction string, config []string) ([]string, error) {
	list, err := d.repo.configured(ctx, config, "remote", "-v")
	if err != nil {
		return nil, err
	}
	var urls []string
	for _, line := range strings.Split(list, "\n") {
		value, matched := strings.CutPrefix(line, name+"\t")
		if url, ok := strings.CutSuffix(value, " ("+direction+")"); matched && ok {
			urls = append(urls, url)
		}
	}
	return urls, nil
}

func (d *delivery) remoteDefault(ctx context.Context) (string, error) {
	switch d.options.deliveryRef {
	case "refs/heads/main", "refs/heads/master", "refs/heads/trunk":
		return "", errors.New("delivery requires an isolated feature branch")
	}
	reply, err := d.repo.configured(ctx, d.config, "ls-remote", "--symref", "--", d.remote, "HEAD")
	if err != nil {
		return "", err
	}
	var symbols, hashes int
	var ref string
	for _, line := range strings.Split(reply, "\n") {
		value, ok := strings.CutSuffix(line, "\tHEAD")
		if !ok {
			continue
		}
		symbol, ok := strings.CutPrefix(value, "ref: ")
		switch {
		case ok:
			symbols++
			ref = symbol
		case objectID.MatchString(value):
			hashes++
		default:
			return "", errors.New("cannot verify a non-default remote branch")
		}
	}
	if symbols != 1 || hashes != 1 || !strings.HasPrefix(ref, "refs/heads/") {
		return "", errors.New("cannot verify a non-default remote branch")
	}
	if err := d.repo.branchRef(ctx, ref); err != nil {
		return "", err
	}
	if d.options.deliveryRef == ref || d.options.deliveryRef == d.prBaseRef {
		return "", errors.New("delivery ref is the remote default or PR base branch")
	}
	return ref, nil
}

func (d *delivery) remoteRef(ctx context.Context, ref string) (string, error) {
	reply, err := d.repo.configured(ctx, d.config, "ls-remote", "--refs", "--", d.remote, ref)
	if err != nil {
		return "", err
	}
	var found string
	for _, line := range strings.Split(reply, "\n") {
		oid, ok := strings.CutSuffix(line, "\t"+ref)
		if !ok {
			continue
		}
		if found != "" || !objectID.MatchString(oid) {
			return "", fmt.Errorf("cannot verify remote ref %s", ref)
		}
		found = oid
	}
	return found, nil
}

func (d *delivery) verifyBase(ctx context.Context, candidate, other string) error {
	if !objectID.MatchString(other) {
		return errors.New("cannot verify PR base revision")
	}
	base, err := d.repo.git(ctx, "merge-base", "--all", other, candidate)
	if err != nil {
		return fmt.Errorf("cannot verify PR merge base; fetch the current base branch first: %w", err)
	}
	if base != d.base {
		return errors.New("PR diff does not match the reviewed base and candidate")
	}
	return nil
}

func (d *delivery) branch() string { return strings.TrimPrefix(d.options.deliveryRef, "refs/heads/") }

func (d *delivery) gh(ctx context.Context, args ...string) (string, error) {
	argv := append([]string{"pr"}, args...)
	result, err := command(ctx, d.repo.directory, "gh", append(argv, "--repo", d.github)...)
	if err != nil {
		return "", fmt.Errorf("gh pr %s: %w", args[0], err)
	}
	return result, nil
}

type prIdentity struct {
	Number int   `json:"number"`
	Cross  *bool `json:"isCrossRepository"`
}

func (d *delivery) openPR(ctx context.Context) (int, error) {
	raw, err := d.gh(ctx, "list", "--state", "open", "--head", d.branch(),
		"--limit", "100", "--json", "number,isCrossRepository")
	if err != nil {
		return 0, err
	}
	var prs []prIdentity
	if json.Unmarshal([]byte(raw), &prs) != nil || prs == nil || len(prs) >= 100 {
		return 0, errors.New("cannot verify the complete list of open PRs for the delivery branch")
	}
	number := 0
	for _, pr := range prs {
		if pr.Cross == nil {
			return 0, errors.New("cannot verify PR repository identity")
		}
		if *pr.Cross {
			continue
		}
		if pr.Number < 1 || number != 0 {
			return 0, errors.New("cannot identify a unique open PR for the delivery branch")
		}
		number = pr.Number
	}
	return number, nil
}

func (d *delivery) numberFromURL(url string) (int, error) {
	prefix := "https://" + d.github + "/pull/"
	if len(url) <= len(prefix) || !strings.EqualFold(url[:len(prefix)], prefix) {
		return 0, errors.New("GitHub returned a PR URL outside the verified repository")
	}
	id := url[len(prefix):]
	number, err := strconv.Atoi(id)
	if err != nil || number < 1 || id != strconv.Itoa(number) {
		return 0, errors.New("GitHub returned an invalid PR number")
	}
	return number, nil
}

func (d *delivery) checkPR(ctx context.Context, expectedHead, candidate string) (string, error) {
	raw, err := d.gh(ctx, "view", strconv.Itoa(d.number), "--json",
		"number,url,state,headRefName,headRefOid,baseRefName,baseRefOid,isCrossRepository")
	if err != nil {
		return "", err
	}
	var pr struct {
		prIdentity
		URL, State, HeadRefName, HeadRefOid, BaseRefName, BaseRefOid string
	}
	if err := json.Unmarshal([]byte(raw), &pr); err != nil {
		return "", errors.New("invalid PR verification result")
	}
	number, err := d.numberFromURL(pr.URL)
	if pr.State != "OPEN" || pr.Cross == nil || *pr.Cross || pr.Number != d.number || err != nil ||
		number != d.number || pr.HeadRefName != d.branch() || pr.HeadRefOid != expectedHead || pr.BaseRefName != d.options.prBase {
		return "", errors.New("PR does not reference the authorized branches and expected head")
	}
	return pr.URL, d.verifyBase(ctx, candidate, pr.BaseRefOid)
}

func (d *delivery) check(ctx context.Context, candidate string) error {
	config, github, err := d.target(ctx)
	if err != nil {
		return err
	}
	if !slices.Equal(config, d.config) || github != d.github {
		return errors.New("effective delivery destination changed")
	}
	defaultRef, err := d.remoteDefault(ctx)
	if err != nil {
		return err
	}
	remoteTip, err := d.remoteRef(ctx, d.options.deliveryRef)
	if err != nil {
		return err
	}
	if defaultRef != d.defaultRef || remoteTip != d.remoteStart {
		return errors.New("remote default branch or delivery candidate changed")
	}
	if d.remoteStart != "" {
		if _, err := d.repo.git(ctx, "merge-base", "--is-ancestor", d.remoteStart, candidate); err != nil {
			return err
		}
	}
	if d.prBaseRef != "" {
		baseTip, err := d.remoteRef(ctx, d.prBaseRef)
		if err != nil {
			return err
		}
		if baseTip == "" {
			return errors.New("cannot verify remote PR base")
		}
		if err := d.verifyBase(ctx, candidate, baseTip); err != nil {
			return err
		}
	}
	if d.github != "" {
		number, err := d.openPR(ctx)
		if err != nil {
			return err
		}
		if number != d.number {
			return errors.New("open PR for the delivery branch does not match the authorized PR")
		}
	}
	if d.number != 0 {
		if d.remoteStart == "" {
			return errors.New("existing PR requires an existing delivery ref")
		}
		_, err := d.checkPR(ctx, d.remoteStart, candidate)
		return err
	}
	return nil
}

func (d *delivery) push(ctx context.Context, candidate string) error {
	if err := d.check(ctx, candidate); err != nil {
		return err
	}
	if err := d.repo.cleanAt(ctx, candidate); err != nil {
		return err
	}
	if _, err := d.repo.configured(ctx, d.config, "push", "--no-follow-tags", "--recurse-submodules=no",
		"--", d.remote, candidate+":"+d.options.deliveryRef); err != nil {
		return err
	}
	remote, err := d.remoteRef(ctx, d.options.deliveryRef)
	if err != nil {
		return err
	}
	if remote != candidate {
		return errors.New("remote SHA differs from reviewed candidate")
	}
	record := Evidence{"candidate": candidate, "base": d.base, "ref": d.options.deliveryRef, "defaultRef": d.defaultRef}
	if d.github != "" {
		if d.number == 0 {
			url, err := d.gh(ctx, "create", "--draft", "--head", d.branch(), "--base", d.options.prBase, "--title", d.options.prTitle, "--body", "")
			if err != nil {
				return err
			}
			if d.number, err = d.numberFromURL(url); err != nil {
				return err
			}
		}
		if record["pr"], err = d.checkPR(ctx, candidate, candidate); err != nil {
			return err
		}
	}
	return writeEvidence(filepath.Join(d.options.evidence, "delivery.json"), record)
}
