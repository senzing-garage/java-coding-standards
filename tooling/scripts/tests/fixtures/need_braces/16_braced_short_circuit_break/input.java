public class Foo
{
    public void method(String s)
    {
        for (int i = 0; i < s.length(); i++) {
            if (s.charAt(i) == ' ') {
                break;
            }
            count++;
        }
    }
}
