document.addEventListener('DOMContentLoaded', function() {
    const discordLoginButton = document.getElementById('discord-login-button');
    const discordLoginSection = document.getElementById('discord-login-section');
    const adminLoginSection = document.getElementById('admin-login-section');
    let clickCount = 0;
    const requiredClicks = 10; // 10번 클릭하면 나타나도록

    if (discordLoginButton && adminLoginSection && discordLoginSection) {
        discordLoginButton.addEventListener('click', function(event) {
            clickCount++;
            console.log("Discord Login Button Clicked. Count:", clickCount); // 디버깅용

            if (clickCount >= requiredClicks) {
                event.preventDefault(); // Discord 로그인 버튼의 기본 동작 방지 (더 이상 클릭 시 Discord로 안 가게)
                discordLoginSection.style.display = 'none'; // Discord 로그인 섹션 숨기기
                adminLoginSection.style.display = 'block'; // 관리자 로그인 섹션 보이기
                clickCount = 0; // 카운트 초기화 (다음 로그인 세션을 위해)

                // Flash messages가 있다면 숨기기 (이전 로그인 시도 실패 메시지 등)
                const flashes = document.querySelector('.flashes');
                if (flashes) {
                    flashes.style.display = 'none';
                }
            } else {
                // 아직 필요한 클릭 횟수에 도달하지 않았으면,
                // 기본 동작(Discord OAuth URL로 이동)이 정상적으로 이루어지도록 함.
                // event.preventDefault()를 호출하지 않습니다.
            }
        });
    }
});