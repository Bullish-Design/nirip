{ pkgs, lib, config, inputs, ... }:

{
  env.GREET = "nirip";
  env.PROJECT_DIR = "/home/andrew/Documents/Projects/nirip";

  packages = [
    pkgs.git
    pkgs.nim
    pkgs.nimble
  ];

  scripts.hello.exec = ''
    echo "hello from $GREET at $PROJECT_DIR"
  '';

  enterShell = ''
    hello
    nim --version
    nimble --version
  '';

  enterTest = ''
    echo "Running tests"
    nim --version
    nimble --version
  '';
}
