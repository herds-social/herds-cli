# Distributing Herds CLI via Homebrew

## Prerequisites

- A **public** GitHub repo for the Homebrew tap: `herds-social/herds-cli-homebrew`
- A GitHub release with the `.tar.gz` source archive (created by the `release-cli.yml` workflow)

## 1. Create the tap repository

Create a public repo named `herds-cli-homebrew` under the `herds-social` GitHub org.

## 2. Add the formula

Create `Formula/herds.rb` in that repo:

```ruby
class Herds < Formula
  include Language::Python::Virtualenv

  desc "CLI for the Herds event platform"
  homepage "https://github.com/herds-social/herds"
  url "https://github.com/herds-social/herds/releases/download/cli-v1.0.0/herds_cli-1.0.0.tar.gz"
  sha256 "REPLACE_WITH_SHA256"
  license "Apache-2.0"

  depends_on "python@3.11"

  # Add each Python dependency as a resource block.
  # Generate these with: pip install homebrew-pypi-poet && poet herds-cli

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Herds CLI Tool", shell_output("#{bin}/herds --help")
  end
end
```

Generate the `resource` blocks automatically:

```bash
pip install homebrew-pypi-poet
poet herds-cli
```

Paste the output into the formula between `license` and `def install`.

## 3. Compute the SHA256

```bash
shasum -a 256 herds_cli-1.0.0.tar.gz
```

Replace `REPLACE_WITH_SHA256` in the formula.

## 4. Install

```bash
brew tap herds-social/herds-cli-homebrew
brew install herds
herds --help
```

## 5. Releasing a new version

1. Tag: `git tag cli-v1.1.0 && git push origin cli-v1.1.0`
2. Wait for the `release-cli.yml` workflow to create the GitHub release
3. Download the `.tar.gz` from the release, compute SHA256
4. Update `url` and `sha256` in `Formula/herds.rb`, push to the `herds-cli-homebrew` repo
