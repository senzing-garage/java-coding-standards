public class Demo
{
    public void run(StringBuilder sb, String first, String second, String third)
    {
        sb.append("alpha")
          .append(
              "beta-and-then-some-more-characters-and-then-finally-the-rest")
          .append("gamma").append(third);
    }
}
