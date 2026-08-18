# SSH를 통한 GitHub 원격 Push 설정 (Remote SSH 환경)

**최종 업데이트: 2026-08-18**

## 개요

이 문서는 **휴대폰 Termius SSH 세션에서 git push를 자동으로 수행**하기 위한 SSH 키 인증 설정 방법입니다.

현재 상황:
- 원격 Windows PC가 켜져 있고 SSH로 접속 가능
- Claude Code가 원격 PC에서 실행 중
- GitHub Push를 자동화하려는 상황

결과:
- `git push` 명령이 인증 없이 자동으로 작동
- 여러 세션에서 동일한 SSH 키로 인증 가능

---

## 1. 사전 요구사항

- 원격 PC에 Git이 설치되어 있음
- GitHub 계정 존재
- 휴대폰에서 Termius SSH로 원격 PC 접속 가능

---

## 2. SSH Key 생성 (첫 번째 세션에서)

**원격 SSH 세션에서 Bash로 실행:**

```bash
ssh-keygen -t ed25519 -C "remote-pc-key" -f ~/.ssh/id_ed25519 -N ""
```

**출력 확인:**
```
Generating public/private ed25519 key pair.
Your identification has been saved in /c/Users/USERNAME/.ssh/id_ed25519
Your public key has been saved in /c/Users/USERNAME/.ssh/id_ed25519.pub
```

---

## 3. Public Key 확인 및 GitHub 등록

### 3.1 Public Key 출력

```bash
cat ~/.ssh/id_ed25519.pub
```

**출력 예시:**
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE3pallr28nUmhoqXxSu7FgvJzPj//irak8vatm6HMfb remote-pc-key
```

### 3.2 GitHub에 등록

**휴대폰 Chrome에서:**

1. `https://github.com/settings/keys` 로 이동
2. "New SSH key" 클릭
3. **Title:** `Remote-Claude-PC` (또는 명확한 라벨)
4. **Key type:** `Authentication Key`
5. **Key 값:** 위의 전체 문자열 복사-붙여넣기
6. "Add SSH key" 클릭

**중요:** Public Key (`.pub`)만 GitHub에 등록합니다. Private Key는 절대 공개하지 마세요.

---

## 4. SSH 연결 테스트

**원격 SSH 세션에서:**

```bash
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null && ssh -T git@github.com
```

**성공 시 출력:**
```
Hi USERNAME! You've successfully authenticated, but GitHub does not provide shell access.
```

---

## 5. Remote URL을 SSH로 변경

### 5.1 현재 Remote 확인

```bash
git remote -v
```

**HTTPS 형태 예시:**
```
origin  https://github.com/USERNAME/REPO.git (fetch)
origin  https://github.com/USERNAME/REPO.git (push)
```

### 5.2 SSH URL로 변경

```bash
git remote set-url origin git@github.com:USERNAME/REPO.git
```

USERNAME과 REPO를 실제 값으로 바꾸세요.

### 5.3 변경 확인

```bash
git remote -v
```

**SSH 형태 예시:**
```
origin  git@github.com:USERNAME/REPO.git (fetch)
origin  git@github.com:USERNAME/REPO.git (push)
```

---

## 6. Git Push 테스트

### 6.1 현재 상태 확인

```bash
git status
```

**예시:**
```
On branch main
Your branch is ahead of 'origin/main' by X commits.
(use "git push" to publish your local commits)
```

### 6.2 Push 실행

```bash
git push -u origin main
```

**첫 번째 push 후에는 단순히:**
```bash
git push
```

**성공 시 출력:**
```
To github.com:USERNAME/REPO.git
   abc1234..def5678  main -> main
branch 'main' set up to track 'origin/main'.
```

### 6.3 완료 확인

```bash
git status
```

**성공 시 출력:**
```
On branch main
Your branch is up to date with 'origin/main'.
nothing to commit, working tree clean
```

---

## 7. 다른 세션에서 동일 설정 적용

새로운 Termius SSH 세션을 열었을 때, 이미 생성된 SSH Key를 자동으로 사용하려면:

### 7.1 SSH Key 확인

```bash
ls -la ~/.ssh/
```

**파일 존재 확인:**
- `id_ed25519` (Private Key - 절대 노출 금지)
- `id_ed25519.pub` (Public Key)
- `known_hosts` (GitHub host key)

### 7.2 원격 저장소 설정 확인

```bash
git remote -v
```

SSH URL이 이미 설정되어 있어야 합니다.

### 7.3 즉시 Push 가능

```bash
git push
```

SSH Key가 이미 존재하고 GitHub에 등록되어 있으면 추가 인증 없이 작동합니다.

---

## 8. Claude Code 자동화

이제 Claude Code에서 다음을 자동으로 실행 가능합니다:

```bash
git add .
git commit -m "message"
git push
```

**세 명령 모두 인증 프롬프트 없이 자동 실행됩니다.**

---

## 9. 문제 해결

### 문제 1: "Permission denied (publickey)"

**원인:** GitHub에 Public Key가 등록되지 않음

**해결:**
1. Public Key 다시 확인: `cat ~/.ssh/id_ed25519.pub`
2. GitHub Settings에서 정확히 등록됐는지 확인
3. 5분 정도 대기 후 재시도

### 문제 2: "Host key verification failed"

**원인:** GitHub host key가 known_hosts에 없음

**해결:**
```bash
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null
```

### 문제 3: "remote: Permission to USERNAME/REPO.git denied"

**원인:** 계정 권한 부족 또는 잘못된 계정

**해결:**
```bash
ssh -T git@github.com
```
로 로그인된 계정 확인

### 문제 4: 새 세션에서 SSH Key를 찾을 수 없음

**원인:** SSH Key가 Windows 사용자 프로필에 저장됨 (세션별로 공유)

**확인:**
```bash
ls ~/.ssh/id_ed25519
```

존재하면 정상입니다.

---

## 10. 보안 주의사항

**절대 하지 마세요:**
- ❌ Private Key (`id_ed25519`) 복사 또는 공유
- ❌ Private Key를 GitHub에 업로드
- ❌ Private Key를 로그에 남기기
- ❌ Private Key가 포함된 파일을 git 커밋

**해도 되는 것:**
- ✅ Public Key (`id_ed25519.pub`) GitHub에 등록
- ✅ Public Key 공유 또는 로그 남기기
- ✅ SSH Key로 여러 세션에서 인증

---

## 11. SSH Key 재생성이 필요한 경우

만약 Private Key가 노출되었다면:

### 11.1 GitHub에서 기존 Key 삭제

Settings → SSH and GPG keys → 해당 Key 삭제

### 11.2 새로운 Key 생성

```bash
rm ~/.ssh/id_ed25519*
ssh-keygen -t ed25519 -C "remote-pc-key" -f ~/.ssh/id_ed25519 -N ""
```

### 11.3 Public Key 다시 등록

위의 "3. Public Key 확인 및 GitHub 등록" 섹션 반복

---

## 12. 참고 링크

- [GitHub SSH Key Setup](https://docs.github.com/en/authentication/connecting-to-github-with-ssh)
- [CLAUDE.md - Git·완료 규칙](../CLAUDE.md#10-git완료-규칙)

---

## 체크리스트

새로운 세션에서 SSH Push를 설정할 때:

- [ ] SSH Key 확인: `ls ~/.ssh/id_ed25519`
- [ ] SSH 연결 테스트: `ssh -T git@github.com`
- [ ] Remote URL 확인: `git remote -v` (SSH 형태여야 함)
- [ ] git push 테스트: `git push`
- [ ] 상태 확인: `git status` ("up to date" 표시)

---

**문서 작성자:** Claude Code  
**유효 범위:** SAAS_WORDS_TWO 프로젝트  
**적용 대상:** 모든 Claude Code 세션 및 Termius SSH 세션
